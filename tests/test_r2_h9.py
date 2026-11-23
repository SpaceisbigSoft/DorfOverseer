"""(r2 h9) Population and the world outside.

From the 15-16 Nov run (R-B.md, R-F.md, R-CE.md) and the plan audit (A3
finding 3, A5 finding 2):
  1. the population cap flipped 29 times in F and 11 in E between the
     survival floor (20) and Growth's 100; then held at 20 three years in E;
  2. B had no migrant and no caravan for ten years: its y251 caravan never
     left (merchants on the map in y261), and nothing said so;
  3. petitions to stay waited unanswered in a fort between closed and
     welcoming (E: 30, the oldest 78 days); a welcoming fort's were left;
  4. no fort had a messenger in its offices (DF's AS_NEEDED post has no slot
     until one is appointed), so Make contact could never run;
  5. 1210 of 1429 site relations read "unknown".

    python tests/test_r2_h9.py
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
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import bridge_hub_src  # noqa: E402  (r8) the hub's text with its catalog and sections
from lua_modules_util import module_src, split_parts, _lua_string  # noqa: E402

# (r9) ai-missions is a hub and parts: the parts' texts handed in (PART_SOURCES), as the
# tests' prelude does, without its reqscript (the module runs here without one)
MISSIONS_SRC = "PART_SOURCES = {" + ", ".join(
    f"[{_lua_string(p)}] = {_lua_string((ROOT / 'lua' / (p + '.lua')).read_text(encoding='utf-8'))}"
    for p in split_parts("ai-missions.lua")) + "}; " + (ROOT / "lua" / "ai-missions.lua").read_text(encoding="utf-8")

from planner import PLANNER_CONFIG, Memory, NEEDS_YOU  # noqa: E402
import planner_growth  # noqa: E402
import planner_outside as O  # noqa: E402
import planner_visitors as V  # noqa: E402
import planner_world  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = PLANNER_CONFIG
DAY = 1200
YEAR = 403200


# ---- 1. the population cap: no flip-flop -----------------------------------------------------

def f_fort(tick: int, drink_pd: float, pop: int = 16, unhappy: int | None = None, beds: int | None = None,
           cap: int = 100, strict: int = 120) -> dict:
    """F in y252 (R-F.md, 20:40-20:53): 16 dwarves, all unhappy, farms, food
    in hand; its drink crossing 15 a dwarf (the "established" line) and back."""
    un = pop if unhappy is None else unhappy
    return {"settings": {"traits": {}, "set_pop_cap": True, "fort_goal": "expand"},
            "society": {"pop_cap": cap, "strict_pop_cap": strict},
            "dwarves": {"total": pop, "adults": pop,
                        "stress": {"miserable": un, "content": pop - un}},
            "stocks": {"drink": int(drink_pd * pop), "prepared_meals": 50 * pop, "plants": 10 * pop},
            "buildings": {"other": {"FarmPlot": 4, "Bed": pop + 4 if beds is None else beds}},
            "date": {"year": 252 + tick // YEAR, "tick": tick % YEAR}}


def run_cap(states: list, memory: Memory) -> list:
    """The cap rule over a run of states, each proposal applied as the game
    would (and booked as planner._done2 does). Returns the caps set."""
    caps = []
    cap, strict = states[0]["society"]["pop_cap"], states[0]["society"]["strict_pop_cap"]
    for s in states:
        s["society"].update(pop_cap=cap, strict_pop_cap=strict)
        props = []
        planner_growth.note_pop_cap(s, memory, CFG)          # note_cycle books the hold
        planner_growth._pop_cap_rule(s, memory, CFG, s["dwarves"]["total"], props, [])
        for p in props:
            cap, strict = p.action["cap"], p.action["strict"]
            caps.append(cap)
            strained = "is strained" in p.reason
            memory.strain_hold = strained
            memory.strain_cap = (min(memory.strain_cap or cap, cap) if strained else None)
    return caps


@test("cap: F's 16 dwarves, 100% unhappy, drink crossing 15 a dwarf every few days: no flip-flop (was 6 flips in 13 min)")
def _():
    m = Memory()
    # day by day for two months: drink 16 a dwarf (established), then 10 (young), alternating every 3 days
    states = [f_fort(d * DAY, 16 if (d // 3) % 2 == 0 else 10) for d in range(60)]
    caps = run_cap(states, m)
    assert caps and caps[0] == 20, caps                  # held at the floor (under it: 20)
    assert len(caps) <= 1, f"the cap flipped: {caps}"


@test("cap: once the strain is gone for good, the hold ends, after the release time and the minimum hold")
def _():
    m = Memory()
    held = [f_fort(d * DAY, 16) for d in range(5)]
    # better for good: everyone content, drink plenty
    good = [f_fort((5 + d) * DAY, 30, unhappy=0) for d in range(40)]
    caps = run_cap(held + good, m)
    assert caps[0] == 20 and caps[-1] == 100 and len(caps) == 2, caps
    # not before the strain was gone h9_pop_cap_release_days and the hold stood h9_pop_cap_min_hold_days
    m2 = Memory()
    caps2 = run_cap(held + good[:CFG["h9_pop_cap_release_days"] - 1], m2)
    assert caps2 == [20], caps2


@test("cap: unhappiness alone holds newcomers out half a year at most when there are beds (E: 3 years at 20)")
def _():
    # E (R-CE.md): 25 dwarves, 40% unhappy, drink and meals fine, beds for all
    m = Memory()
    days = list(range(0, 200, 2))
    states = [f_fort(d * DAY, 20, pop=25, unhappy=10, cap=100, strict=120) for d in days]
    notes_all = []
    caps = run_cap(states, m)
    assert caps[0] == 25 and caps[-1] == 100, caps
    assert m.pop_cap_hold.get("unhappy_spent") is True
    # the same with beds short (crowding): the hold stays
    m2 = Memory()
    states2 = [f_fort(d * DAY, 20, pop=25, unhappy=10, beds=20) for d in days]
    caps2 = run_cap(states2, m2)
    assert caps2 == [25], caps2
    # drink short still holds (survival)
    s = f_fort(300 * DAY, 1, pop=25, unhappy=10)
    s["society"].update(pop_cap=100, strict_pop_cap=120)
    props = []
    planner_growth.note_pop_cap(s, m, CFG)
    planner_growth._pop_cap_rule(s, m, CFG, 25, props, notes_all)
    assert props and props[0].action["cap"] == 25 and "drink" in props[0].reason, (props, notes_all)


@test("cap: F's first flips (Galena y250): drink 1.8, then 5, then 0 a dwarf within days: held once, never let go between")
def _():
    m = Memory()
    seq = [1.8] * 2 + [5] * 3 + [0] * 3 + [5] * 4
    caps = run_cap([f_fort(d * DAY, dr, pop=5, unhappy=0) for d, dr in enumerate(seq)], m)
    assert caps == [20], caps
    # an open cap newly short of drink holds at once (survival), however recently it opened
    m2 = Memory()
    m2.pop_cap_hold = {"regime": "open", "since": 252 * YEAR}
    caps = run_cap([f_fort(DAY, 1.0, pop=25, unhappy=0)], m2)
    assert caps == [25], caps


@test("cap: a young fort's unhappy line counts while it is held (the cause of F's flips)")
def _():
    s = f_fort(0, 10)          # young (drink under 15 a dwarf), 100% unhappy, drink over the 4 to let go
    assert not planner_growth.fort_strain(s, CFG, False)         # a young fort isn't held for its moods...
    assert planner_growth.fort_strain(s, CFG, True)              # ...but a held one isn't let go for being young


# ---- 2. the migrant drought and the caravan that never left -----------------------------------

def b_fort(tick: int, pop: int = 13, caravans=None, cap: int = 100, **kw) -> dict:
    """B, y251-y261 (R-B.md): 13 dwarves, the cap open, force Migrants there."""
    s = {"settings": {"traits": {"outsiders": 60}, "set_pop_cap": True, "fort_goal": "expand"},
         "society": {"pop_cap": cap, "strict_pop_cap": cap + 20},
         "dwarves": {"total": pop}, "stocks": {"drink": 20 * pop, "prepared_meals": 20 * pop},
         "migration": {"civ": True, "force": "force", "hermit_tool": False, "queued": 0},
         "others_on_map": {}, "date": {"year": 251 + tick // YEAR, "tick": tick % YEAR}}
    if caravans is not None:
        s["migration"]["caravans"] = caravans
    s.update(kw)
    return s


STUCK = [{"entity": 308, "own": True, "state": "Leaving", "days_left": 0, "merchants": 2, "can_leave": 2,
          "leaving": True}]


def drought(states: list, memory: Memory) -> list:
    out = []
    for s in states:
        props, notes = [], []
        O.note_outside(s, memory, CFG)               # note_cycle books, plan() reads
        O._drought_rule(s, memory, CFG, props, notes)
        out.append((props, notes))
    return out


@test("drought: B's caravan leaving with its merchants on the map: seen stuck after 28 days, merchants told to leave")
def _():
    m = Memory()
    r = drought([b_fort(d * DAY, caravans=STUCK) for d in range(0, 40, 4)], m)
    first = next(i for i, (p, _) in enumerate(r) if p)
    assert first * 4 >= CFG["h9_caravan_stuck_days"], first
    p = r[first][0][0]
    assert p.rule == "stuck_caravan" and p.action == {"type": "free_caravan", "entity": 308}, p
    # after two tries (each booked by the rule's last_fired), a Needs you instead
    m2 = Memory()
    t = 0
    for i in range(12):
        props, notes = [], []
        O.note_outside(b_fort(t, caravans=STUCK), m2, CFG)
        O._drought_rule(b_fort(t, caravans=STUCK), m2, CFG, props, notes)
        if props:
            m2.last_fired["stuck_caravan"] = 251 * YEAR + t          # done (record() books it)
        t += 30 * DAY
    assert not props and any(n.startswith(NEEDS_YOU) and "12624" in n for n in notes), notes
    # no way to the edge: a Needs you to open it, no action
    shut = [dict(STUCK[0], can_leave=0)]
    m3 = Memory()
    r3 = drought([b_fort(d * DAY, caravans=shut) for d in range(0, 40, 4)], m3)
    assert not any(p for p, _ in r3) and any("way to the map's edge" in n for n in r3[-1][1]), r3[-1]


@test("drought: ten years without migrants is reported with its cause (the stuck caravan), not silent")
def _():
    m = Memory()
    r = drought([b_fort(d * 7 * DAY, caravans=STUCK) for d in range(0, 40)], m)
    notes = [n for _, ns in r for n in ns]
    assert any(n.startswith("MIGRANT DROUGHT") and "leaving" in n and "12624" in n for n in notes), notes[-5:]
    assert m.outside["drought"]["cause"] == "caravan"


@test("drought: no cause the AI can see: a wave called once a season, at most three that brought nobody")
def _():
    m = Memory()
    calls, t = 0, 0
    for i in range(60):
        props, notes = [], []
        O.note_outside(b_fort(t), m, CFG)
        O._drought_rule(b_fort(t), m, CFG, props, notes)
        if props:
            assert props[0].action == {"type": "call_migrants"} and props[0].rule == "migrant_drought"
            calls += 1
            m.last_fired["migrant_drought"] = 251 * YEAR + t          # done (record() books it)
        t += 14 * DAY
    assert calls == CFG["h9_drought_max_calls"], calls
    assert any("brought nobody" in n for n in notes), notes
    # a wave came: the count starts again
    props, notes = [], []
    O.note_outside(b_fort(t, pop=20), m, CFG)
    O._drought_rule(b_fort(t, pop=20), m, CFG, props, notes)
    assert m.outside["last_wave"] == 251 * YEAR + t and not props


@test("drought: the cause is the cap (the AI's or the player's), the hermit tool or a gone civ: no wave called")
def _():
    from planner_core import abs_tick
    for kw, want, you in ((dict(cap=13), "cap", False), (dict(cap=13, settings={"traits": {}, "set_pop_cap": False,
                                                                                 "fort_goal": "expand"}), "cap", True)):
        m = Memory()
        last = None
        for d in range(0, 300, 10):
            s = b_fort(d * DAY, **kw)
            props, notes = [], []
            O.note_outside(s, m, CFG)
            O._drought_rule(s, m, CFG, props, notes)
            last = (props, notes)
        assert not last[0] and m.outside["drought"]["cause"] == want, (last, m.outside)
        assert any(n.startswith(NEEDS_YOU) for n in last[1]) == you, last[1]
    m = Memory()
    for d in range(0, 300, 10):
        s = b_fort(d * DAY)
        s["migration"]["hermit_tool"] = True
        props, notes = [], []
        O.note_outside(s, m, CFG)
        O._drought_rule(s, m, CFG, props, notes)
    assert not props and m.outside["drought"]["cause"] == "hermit" and any("hermit" in n for n in notes)
    # Maintain or Extreme-low Growth: no newcomers on purpose, no drought
    m = Memory()
    for d in range(0, 300, 10):
        s = b_fort(d * DAY)
        s["settings"]["fort_goal"] = "maintain"
        props, notes = [], []
        O.note_outside(s, m, CFG)
        O._drought_rule(s, m, CFG, props, notes)
    assert not props and "drought" not in m.outside


@test("drought: a fallen fort's waves stay the recovery's (never two callers)")
def _():
    m = Memory()
    m.recovery = {"since": 0, "why": "x", "floor": 15}
    props = []
    for d in range(0, 300, 10):
        props = []
        O.note_outside(b_fort(d * DAY), m, CFG)
        O._drought_rule(b_fort(d * DAY), m, CFG, props, [])
    assert not props


CARAVAN_FAKE = r"""
local src = ...
local W = {}
local env = setmetatable({}, {__index = _G})
env.CR_OK = 0
local function unit(id, civ, x, grp)
  return {id = id, civ_id = civ, pos = {x = x, y = 0, z = 0, grp = grp},
          flags1 = {merchant = true, left = false, inactive = false, forest = false}, animal = {leave_countdown = 0}}
end
W.u1, W.u2, W.u3 = unit(1, 308, 1, 7), unit(2, 308, 2, 9), unit(3, 400, 3, 7)
env.df = {global = {timed_events = {}, plotinfo = {civ_id = 308,
            caravans = {{entity = 308, trade_state = 3, time_remaining = 0, flags = {tribute = false}},
                        {entity = 400, trade_state = 2, time_remaining = 5000, flags = {tribute = false}}}},
                    world = {units = {active = {W.u1, W.u2, W.u3}}}},
          caravan_state = {T_trade_state = {[1] = 'Approaching', [2] = 'AtDepot', [3] = 'Leaving'}},
          timed_event_type = {Migrants = 2},
          historical_entity = {find = function(id) return {id = id} end}}
env.dfhack = {findScript = function(n) return n == 'force' and 'x' or nil end,
              units = {isDead = function() return false end},
              maps = {getWalkableGroup = function(p) return p.grp end}}
env.reqscript = function(name)
    if name == 'ai-way-out' then return {edge_groups = function() return {[7] = true} end} end
    error('no module ' .. tostring(name))
end
assert(load(src, 'ai-recovery', 't', env))()
return env, W
"""


@test("lua: the migration report lists every caravan with its merchants and whether they can leave; free_caravan")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(CARAVAN_FAKE, module_src("ai-recovery.lua"))
    r = env.report()
    cs = list(r.caravans.values())
    assert len(cs) == 2, cs
    c = [x for x in cs if x.entity == 308][0]
    assert c.own is True and c.state == "Leaving" and c.merchants == 2 and c.can_leave == 1 and c.leaving, dict(c)
    other = [x for x in cs if x.entity == 400][0]
    assert other.state == "AtDepot" and other.merchants == 1 and other.leaving is None, dict(other)
    d = env.free_caravan(308, True)
    assert d.ok and d.dry_run and d.told == 1 and d.shut == 1 and not w.u1.flags1.forest, dict(d)
    d = env.free_caravan(308, False)
    assert d.ok and w.u1.flags1.forest is True and w.u1.animal.leave_countdown == 2 and not w.u2.flags1.forest, dict(d)
    assert env.free_caravan(400, False).ok is False            # trading: left alone
    assert env.free_caravan(999, False).ok is False




@test("plan() writes no memory: the cap's hold, the drought and the petitions' first sight are booked by note_cycle")
def _():
    import planner
    s = b_fort(300 * DAY, caravans=STUCK)
    s.update(f_fort(300 * DAY, 16))
    s["migration"] = b_fort(0, caravans=STUCK)["migration"]
    m = Memory()
    for d in range(0, 300, 30):
        st = copy.deepcopy(s)
        st["date"]["tick"] = d * DAY
        planner.note_cycle(st, m)
    snap = json.dumps(m.to_dict(), sort_keys=True, default=str)
    planner.plan(copy.deepcopy(s), m)
    assert json.dumps(m.to_dict(), sort_keys=True, default=str) == snap
    assert m.pop_cap_hold.get("regime") and m.outside.get("leaving"), (m.pop_cap_hold, m.outside)


@test("bridge: free_caravan wired (dry run), its words, the survival class; the drought rule runs in plan()")
def _():
    b = bridge_hub_src()
    assert re.search(r"free_caravan = function\(a\)[\s\S]{0,300}reqscript\('ai-recovery'\)\.free_caravan\(", b)
    dry = b[b.index("DRY_OK = {}"):b.index("}) do DRY_OK[name] = true end")]
    assert "'free_caravan'" in dry
    import overseer
    import hold_classes
    assert "free_caravan" in overseer.SHORT_WORDS and "free_caravan" in hold_classes._SURVIVAL_ACTIONS
    assert hold_classes.RULE_CLASS.get("migrant_drought") and hold_classes.RULE_CLASS.get("stuck_caravan")
    src = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    assert "_guard(_drought_rule, s, memory, cfg, proposals, notes)" in src


# ---- 3. petitions to stay: every one answered ----------------------------------------------

def e_fort(outsiders, pending, beds=40, pop=30, tavern=True, library=False, **kw):
    """E (A3 finding 3): Outsiders between -50 and 30, petitions to stay waiting (82 and 24 days)."""
    s = {"settings": {"traits": {"outsiders": outsiders, "militarism": 0}, "accept_visitors": True},
         "dwarves": {"total": pop, "stress": {"content": pop}},
         "stocks": {"drink": 20 * pop, "prepared_meals": 30 * pop},
         "buildings": {"other": {"Bed": beds}},
         "locations": {"count": {**({"INN_TAVERN": 1} if tavern else {}), **({"LIBRARY": 1} if library else {})}},
         "petitions": {"pending": pending, "orders": {}, "residents": []},
         "date": {"year": 256, "tick": 1000}}
    s.update(kw)
    return s


def pet(i, reason="entertain_people", days=10, **kw):
    return {"id": i, "type": "Residency", "name": f"Bard {i}", "reason": reason, "days": days,
            "applicant": {"unit": 100 + i, "on_map": True, "hf": i}, **kw}


E_PENDING = [pet(1, days=82), pet(2, days=82), pet(3, "eradicate_beasts", days=78)]


@test("residency: a neutral fort (E) answers every petition: none left pending (was 'stale': 30 waiting, 78 days)")
def _():
    m = Memory()
    s = e_fort(0, E_PENDING)
    props, notes = [], []
    V._residency_rule(s, m, CFG, props, notes)
    assert props, notes        # was: nothing at all
    # run it to the end, answering what the AI proposes
    pending = list(E_PENDING)
    for _ in range(5):
        props, notes = [], []
        V._residency_rule(e_fort(0, pending), m, CFG, props, notes)
        if not props:
            break
        ids = props[0].action.get("ids") or [props[0].action.get("id")]
        pending = [e for e in pending if e["id"] not in ids]
    assert not pending, (pending, notes)


@test("residency: neutral forts weigh by room and character: no beds, no food or no tavern for a bard: declined")
def _():
    m = Memory()
    for kw, why in ((dict(beds=30), "spare bed"), (dict(tavern=False), "no tavern"),
                    (dict(stocks={"drink": 30, "prepared_meals": 30}), "food")):
        props = []
        V._residency_rule(e_fort(0, [pet(1)], **kw), m, CFG, props, [])
        assert props and props[0].action["accept"] is False and why in props[0].reason, (kw, props)
    # Outsiders below 0: a visitor who brings nothing the fort needs is declined; a bard with a tavern isn't
    props = []
    V._residency_rule(e_fort(-30, [pet(1, "other_reason")]), m, CFG, props, [])
    assert props and props[0].action["accept"] is False, props
    ok, why = V.residency_verdict(pet(1), e_fort(-30, [pet(1)]), CFG, "weigh")
    assert ok, why
    # a scholar wants a library
    assert not V.residency_verdict(pet(2, "study"), e_fort(10, []), CFG, "weigh")[0]
    assert V.residency_verdict(pet(2, "study"), e_fort(10, [], library=True), CFG, "weigh")[0]
    # mercenaries by Militarism; a vampire never
    assert not V.residency_verdict(pet(3, "make_a_living_as_a_warrior"), e_fort(10, []), CFG, "weigh")[0]
    assert not V.residency_verdict(pet(4, vampire=True), e_fort(100, []), CFG, "accept")[0]


@test("residency: one the fort would take waits for you on DF's screen, then is declined (never pending for ever)")
def _():
    m = Memory()
    # young petitions: a Needs you (the AI can't agree), nothing declined
    props, notes = [], []
    V._residency_rule(e_fort(60, [pet(1, days=5)]), m, CFG, props, notes)
    assert not props and any(n.startswith(NEEDS_YOU) and "petitions screen" in n for n in notes), notes
    # past h9_residency_player_days: declined, said plainly
    props, notes = [], []
    V._residency_rule(e_fort(60, [pet(1, days=CFG["h9_residency_player_days"])]), m, CFG, props, notes)
    assert props and props[0].action["accept"] is False and "can't agree" in props[0].reason, props
    # a welcoming fort's vampire is declined at once (was left waiting)
    props = []
    V._residency_rule(e_fort(60, [pet(1, vampire=True, days=1)]), m, CFG, props, [])
    assert props and props[0].action == {"type": "answer_petition", "ids": [1], "accept": False,
                                         "residency": True}, props
    # no days in an older report: the AI's own first sight counts
    m2 = Memory()
    p0 = dict(pet(1), days=None)
    V.note_residency(e_fort(60, [p0]), m2)
    V._residency_rule(e_fort(60, [p0]), m2, CFG, [], [])
    s = e_fort(60, [p0])
    s["date"]["tick"] += CFG["h9_residency_player_days"] * DAY
    props = []
    V.note_residency(s, m2)
    V._residency_rule(s, m2, CFG, props, [])
    assert props and props[0].action["accept"] is False, props


@test("residency: the README no longer says DF's standing orders answer petitions on 53.17-r1")
def _():
    src = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "needs a DFHack newer than 53.16-r3. On 53.16-r3 they wait for you" not in src


# ---- 4. the messenger: a slot made as DF's nobles screen does -------------------------------

@test("messenger: Make contact on, the fort's messenger has no slot yet (AS_NEEDED): appoint (the bridge adds it)")
def _():
    s = {"settings": {"make_contact": True, "appoint_nobles": True, "send_messenger": False},
         "dwarves": {"total": 40}, "stocks": {"drink": 2000, "prepared_meals": 2000},
         "buildings": {"other": {"FarmPlot": 4}},
         "offices": {"offices": {"MESSENGER": {"vacant": 0, "held": [], "slots": 0, "no_slot": True,
                                                "appointable": True}}, "messenger": {"position": True, "slots": 0}},
         "date": {"year": 256, "tick": 1000}}
    props, notes = [], []
    planner_world._messenger_rule(s, CFG, props, notes)
    assert props and props[0].action == {"type": "appoint", "office": "MESSENGER"}, (props, notes)
    # no position at all: said plainly, nothing proposed
    s["offices"] = {"offices": {}, "messenger": {"position": False}}
    props, notes = [], []
    planner_world._messenger_rule(s, CFG, props, notes)
    assert not props and any("no messenger position" in n for n in notes), notes
    # off by default: nothing
    s["settings"]["make_contact"] = False
    s["offices"]["offices"]["MESSENGER"] = {"vacant": 0, "held": [], "slots": 0, "no_slot": True}
    props = []
    planner_world._messenger_rule(s, CFG, props, [])
    assert not props


NOBLES_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local function vec(t)
  t = t or {}
  return setmetatable(t, {__index = {insert = function(self, pos, v) table.insert(self, v) end,
                                     erase = function(self, i) table.remove(self, i + 1) end}})
end
local function ivec(t)       -- a 0-based vector
  local v = {n = #t}
  for i, x in ipairs(t) do v[i - 1] = x end
  return setmetatable(v, {__len = function(self) return self.n end,
    __index = {insert = function(self, pos, x) self[self.n] = x; self.n = self.n + 1 end,
               erase = function(self, i) for k = i, self.n - 2 do self[k] = self[k + 1] end; self[self.n - 1] = nil; self.n = self.n - 1 end}})
end
local function ipairs0(v)
  if getmetatable(v) and v.n then
    local i = -1
    return function() i = i + 1; if i < v.n then return i, v[i] end end
  end
  return ipairs(v)
end
env.ipairs = ipairs0
local LEADER = {id = 1, code = 'EXPEDITION_LEADER', appointed_by = ivec({}), flags = {}, responsibilities = {}, number = 1}
local MESS = {id = 7, code = 'MESSENGER', appointed_by = ivec({1}), flags = {}, responsibilities = {}, number = -1}
local ENT = {id = 50, positions = {own = ivec({LEADER, MESS}), assignments = ivec({{id = 0, position_id = 1, histfig = 900, flags = {active = true}, squad_id = -1}}),
             next_assignment_id = 1}, assignments_by_type = ivec({})}
local HF = {id = 901, entity_links = ivec({}), name = 'Talker'}
local U = {id = 11, hist_figure_id = 901, military = {squad_id = -1}, status = {current_soul = {skills = ivec({})}}, mood = -1}
env.W = {ENT = ENT, HF = HF}
env.df = {global = {cur_year = 256, cur_year_tick = 0, hist_event_next_id = 1, world = {history = {events = ivec({})}},
                    plotinfo = {group_id = 50, civ_id = 40, site_id = 1}},
          historical_entity = {find = function(id) if id == 50 then return ENT end end},
          job_skill = {}, entity_position_assignment = {new = function() return {flags = {}} end},
          histfig_entity_link_positionst = {is_instance = function(l) return l.assignment_id ~= nil end},
          history_event_add_hf_entity_linkst = {}, histfig_entity_link_type = {POSITION = 1},
          historical_figure = {find = function(id) if id == 901 then return HF end end},
          unit = {find = function(id) if id == 11 then return U end end}}
env.dfhack = {units = {getNoblePositions = function(u)
                  for _, l in ipairs0(HF.entity_links) do
                    for _, a in ipairs0(ENT.positions.assignments) do
                      if a.id == l.assignment_id and a.histfig == 901 then return {{position = MESS}} end
                    end
                  end
                  return {} end,
                getReadableName = function() return 'Talker' end, isChild = function() return false end,
                isBaby = function() return false end, getStressCategory = function() return 4 end,
                getCitizens = function() return {U} end},
              translation = {translateName = function(n) return n end}}
env.reqscript = function(name)
  if name == 'ai-util' then return {fort_entity = function() return ENT end,
                                    citizens = function() return {U} end} end
  error('no module ' .. name)
end
assert(load(src, 'ai-nobles', 't', env))()
env.MESSENGER_HOLD = false   -- (r14 hold) these tests check the appointment itself
return env
"""


@test("lua: the messenger's position with no slot is reported; appoint adds a slot and fills it (dry run adds none)")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(NOBLES_FAKE, module_src("ai-nobles.lua"))
    r = env.survey(None)
    o = r.offices.MESSENGER
    assert o is not None and o.no_slot is True and o.appointable is True and r.messenger.position is True, dict(r)
    d = env.appoint("MESSENGER", True, None)
    assert d.ok and d.dry_run and d.slot_added and env.W.ENT.positions.assignments.n == 1, dict(d)
    a = env.appoint("MESSENGER", False, None)
    assert a.ok is True and a.slot_added is True, dict(a)
    ents = env.W.ENT.positions
    assert ents.assignments.n == 2 and ents.next_assignment_id == 2 and ents.assignments[1].histfig == 901, dict(a)
    r = env.survey(None)
    assert list(r.offices.MESSENGER.held.values()) == ["Talker"], dict(r.offices.MESSENGER)


# ---- 5. site relations, both ways -----------------------------------------------------------

@test("missions: a site's relation read both ways and through the fort's government; never met is NoContact")
def _():
    need_lua()
    tm = (ROOT / "tests" / "test_missions.py").read_text(encoding="utf-8")
    fake = re.search(r'FAKE = r"""(.*?)"""', tm, re.S).group(1)
    lua = LuaRuntime(unpack_returned_tuples=True)

    def world(setup):
        return lua.execute(fake, MISSIONS_SRC, setup)

    def lst(t):
        return [t[i] for i in range(1, len(t) + 1)]
    env = world(r"""
B.entity(300)                                 -- a goblin civ that lists us (we don't list it)
table.insert(B.ENTS[300].relations.diplomacy.state, B.S{group_id = 100, relation = 1})   -- War
B.entity(600)                                 -- a civ that lists our government (200), tribute it accepts
table.insert(B.ENTS[600].relations.diplomacy.state, B.S{group_id = 200, relation = 2})
B.entity(700)                                 -- a civ neither side lists: never met
B.entity(800)                                 -- listed by our government
table.insert(B.ENTS[200].relations.diplomacy.state, B.S{group_id = 800, relation = 0})   -- Peace
B.site(21, 'Gob', 300, 51, 50)
B.site(22, 'Tributary', 600, 52, 50)
B.site(23, 'Stranger', 700, 53, 50)
B.site(24, 'Friend', 800, 54, 50)
B.site(25, 'Ghost civ', 999, 55, 50)          -- no entity at all: unknown
B.env.df.diplomacy_state_type = {[0] = 'Peace', [1] = 'War', [2] = 'AcceptingTribute'}
""")
    s = env.report().sites
    rel = {n.id: n.relation for n in lst(s.nearest)}
    assert rel == {21: "War", 22: "OfferingTribute", 23: "NoContact", 24: "Peace", 25: "unknown"}, rel
    assert s.n_unknown == 1 and s.n_hostile == 1, (s.n_unknown, s.n_hostile)


if __name__ == "__main__":
    finish()
