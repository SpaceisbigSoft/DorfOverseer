"""(0.105.30, mood fixes) The forensic review of 8 Nov's live logs: two
citizens dead of failed strange moods, a third (F's Armorer) going the same
way.

1. F: a fey mood waited for 1 bone; the fort's bone lay out of the dwarf's
   walk and the Beast-friends ban (no_slaughter) held, so nothing acted. A
   mood now sets the ban aside for one animal (the oldest spare adult, one a
   mood, said plainly), and "out of reach" is one Needs you, never "no bone"
   beside it.
2. D: a secretive mood had no line for 40 days. A mood that fetched nothing
   for 7 days is said in Needs you with the bridge's counts, and each mood's
   requests go to the journal once a day.
3. E: "no loose stone" said 70 s before the artifact: stone the dwarf holds,
   and a search cut short, are not "none".
4. The death line: the dead dwarf's own berserk mood is said as theirs.

    python tests/test_mood_fixes.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

import planner  # noqa: E402
import planner_moods  # noqa: E402
from planner import Memory, PLANNER_CONFIG, abs_tick, note_cycle, plan, record, TICKS_PER_DAY  # noqa: E402
from planner_core import mood_on_hand  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
NEEDS = planner.NEEDS_YOU


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["orders"] = []
    s["buildings"]["workshops"]["Butchers"] = 1
    s["others_on_map"]["tame_animals"] = 30
    return s


def av(**kw):
    a = {"free": 0, "reach": 0, "forbidden": 0, "forbidden_reach": 0, "dump": 0, "job": 0, "other": 0}
    a.update(kw)
    return a


def mood(missing, **kw):
    m = {"unit_id": 5, "name": "Logem", "mood": "Fey", "craft": True, "skill": "FORGE_ARMOR",
         "workshop": "MetalsmithsForge", "items_have": 0, "items_needed": len(missing), "missing": missing}
    m.update(kw)
    return m


def beast_friends() -> Memory:
    m = Memory()
    m.culture = {"quirks": {"beast_friends": {"year": 250, "why": "test"}}}
    return m


BONE_FAR = {"index": 0, "item": "NONE", "quantity": 1, "flags": ["bone"], "avail": av(free=4, reach=0)}


def mood_props(props):
    return [p for p in props if p.rule == "mood"]


@test("F: Beast-friends: a mood's bone out of reach sends the oldest spare animal to the butcher, said plainly")
def _():
    s = fort()
    s["moods"] = {"list": [mood([dict(BONE_FAR)])]}
    m = beast_friends()
    m.moods_seen = {"5": abs_tick(s)}
    assert planner_moods.has_rule(m.culture, "no_slaughter")
    props, notes = plan(s, m)
    sl = [p for p in mood_props(props) if p.action.get("type") == "slaughter_one"]
    assert len(sl) == 1, [p.action for p in mood_props(props)]
    assert sl[0].action == {"type": "slaughter_one", "oldest": True, "mood_unit": 5}, sl[0].action
    assert "the fort's Beast-friends ban is set aside to save Logem's mood" in sl[0].reason, sl[0].reason
    assert "one animal only" in sl[0].reason, sl[0].reason
    # no "no bone", no contradictory pair
    assert not any("no bone" in n or "can't supply" in n for n in notes), notes
    assert not any(n.startswith(NEEDS) and "Logem" in n for n in notes), notes


@test("F: the ban still holds outside a mood (the soap rule's slaughter is not freed)")
def _():
    s = fort()
    acts = []
    assert planner_moods._mood_slaughter(s, beast_friends(), PLANNER_CONFIG, acts, "fat") is False and acts == []
    assert planner_moods._mood_slaughter(s, Memory(), PLANNER_CONFIG, acts, "fat") is True
    assert acts[0][0] == {"type": "slaughter_one"}, acts


@test("F: one animal a mood: once one went (recorded on success), no second; record() keeps it")
def _():
    s = fort()
    s["moods"] = {"list": [mood([dict(BONE_FAR)])]}
    m = beast_friends()
    m.moods_seen = {"5": abs_tick(s)}
    props, _ = plan(s, m)
    sl = [p for p in mood_props(props) if p.action.get("type") == "slaughter_one"][0]
    record([(sl, {"ok": True, "unit_id": 99})], s, m)
    assert m.mood_slaughter == {"5": abs_tick(s)}, m.mood_slaughter
    props, notes = plan(s, m)
    assert not any(p.action.get("type") == "slaughter_one" for p in props), [p.action for p in props]
    assert not any("no bone" in n for n in notes), notes
    # forgotten when the mood ends
    s["moods"] = {"list": []}
    note_cycle(s, m)
    assert m.mood_slaughter == {}, m.mood_slaughter


@test("F: bone out of reach and no butcher's: one Needs you (out of the dwarf's walk), never 'no bone' beside it")
def _():
    s = fort()
    s["buildings"]["workshops"].pop("Butchers", None)
    s["moods"] = {"list": [mood([dict(BONE_FAR)])]}
    m = beast_friends()
    m.moods_seen = {"5": abs_tick(s)}
    notes = plan(s, m)[1]
    asks = [n for n in notes if n.startswith(NEEDS) and "Logem" in n]
    assert len(asks) == 1, asks
    assert "where the dwarf can't walk" in asks[0] and "1 bone" in asks[0], asks
    assert "no butcher's" in asks[0], asks
    assert "no bone and no spare tame animal" not in asks[0] and "can't supply" not in asks[0], asks


@test("F: bone truly absent, no butcher's: 'can't supply' says why (no butcher's), not the old pair")
def _():
    s = fort()
    s["buildings"]["workshops"].pop("Butchers", None)
    s["moods"] = {"list": [mood([{"index": 0, "item": "NONE", "quantity": 1, "flags": ["bone"], "avail": av()}])]}
    m = Memory()
    m.moods_seen = {"5": abs_tick(s)}
    asks = [n for n in plan(s, m)[1] if n.startswith(NEEDS) and "Logem" in n]
    assert len(asks) == 1 and "can't supply" in asks[0] and "no butcher's" in asks[0], asks
    assert "can't walk" not in asks[0], asks


@test("lua: slaughter_pick(oldest) takes the oldest of the kind and sex; without it, as before")
def _():
    from lupa.lua53 import LuaRuntime
    src = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    body = re.search(r"\nfunction slaughter_pick\(.*?\nend\n", src, re.S).group(0)
    L = LuaRuntime(unpack_returned_tuples=True)
    L.execute(body)
    pick = L.globals().slaughter_pick

    def t(x):
        return L.table_from({k: v for k, v in x.items()})
    cows = L.table_from([t({"id": i, "race": "COW", "male": m, "born": b})
                         for i, m, b in ((1, True, 500), (2, True, 100), (3, True, 300), (4, False, 50))])
    p, race, n = pick(cows, True)
    assert race == "COW" and n == 4 and p.id == 2, (p.id, race, n)     # the oldest male (one female: kept)
    p, _, _ = pick(cows)
    assert p.id == 1, p.id                                                # as before: by id


@test("D: a mood that fetched nothing for 7 days is said in Needs you with the counts, though all reads on hand")
def _():
    s = fort()
    s["moods"] = {"list": [mood([{"index": 0, "item": "NONE", "quantity": 1, "flags": ["bone"],
                                  "avail": av(free=3, reach=3, enough=True)}], mood="Secretive", name="Åblel")]}
    m = Memory()
    now = abs_tick(s)
    m.moods_seen = {"5": now - 8 * TICKS_PER_DAY}
    m.mood_progress = {"5": {"have": 0, "since": now - 3 * TICKS_PER_DAY}}
    notes = plan(s, m)[1]
    assert not any(n.startswith(NEEDS) and "Åblel" in n for n in notes), notes      # 3 days: not yet
    m.mood_progress = {"5": {"have": 0, "since": now - 8 * TICKS_PER_DAY}}
    asks = [n for n in plan(s, m)[1] if n.startswith(NEEDS) and "Åblel" in n]
    assert len(asks) == 1, asks
    assert "fetched nothing for 8 days" in asks[0] and "1 bone: 3 free (3 in walk)" in asks[0], asks
    assert PLANNER_CONFIG["mood_stall_days"] == 7


@test("D: a stalled mood that also lacks: one Needs you, the counts added to it")
def _():
    s = fort()
    s["buildings"]["workshops"].pop("Butchers", None)
    s["moods"] = {"list": [mood([{"index": 0, "item": "NONE", "quantity": 1, "flags": ["bone"], "avail": av()}])]}
    m = Memory()
    now = abs_tick(s)
    m.moods_seen = {"5": now - 9 * TICKS_PER_DAY}
    m.mood_progress = {"5": {"have": 0, "since": now - 9 * TICKS_PER_DAY}}
    asks = [n for n in plan(s, m)[1] if n.startswith(NEEDS) and "Logem" in n]
    assert len(asks) == 1 and "can't supply" in asks[0] and "no progress for 9 days" in asks[0], asks


@test("D: note_cycle keeps each mood's progress: the clock restarts when it fetches something")
def _():
    s = fort()
    s["moods"] = {"list": [mood([dict(BONE_FAR)], items_have=1)]}
    m = Memory()
    note_cycle(s, m)
    now = abs_tick(s)
    assert m.mood_progress == {"5": {"have": 1, "since": now}}, m.mood_progress
    m.mood_progress["5"]["since"] = now - 5 * TICKS_PER_DAY
    note_cycle(s, m)
    assert m.mood_progress["5"]["since"] == now - 5 * TICKS_PER_DAY        # no change: the clock runs
    s["moods"]["list"][0]["items_have"] = 2
    note_cycle(s, m)
    assert m.mood_progress["5"] == {"have": 2, "since": now}, m.mood_progress
    s["moods"] = {"list": []}
    note_cycle(s, m)
    assert m.mood_progress == {}


@test("D: each mood's requests go to the journal once a game day, compactly; the overseer writes them")
def _():
    s = fort()
    s["moods"] = {"list": [mood([dict(BONE_FAR), {"index": 1, "item": "BAR", "quantity": 1, "flags": ["metal"],
                                                  "avail": av(free=2, reach=2, enough=True, capped=True)}])]}
    m = Memory()
    m.moods_seen = {"5": abs_tick(s) - 2 * TICKS_PER_DAY}
    e = planner_moods.mood_journal(s, m)
    assert len(e) == 1 and e[0]["unit_id"] == 5 and e[0]["day"] == 2, e
    r = e[0]["requests"]
    assert r[0] == {"what": "1 bone", "on_hand": False, "avail": {"free": 4}}, r
    assert r[1]["avail"] == {"free": 2, "reach": 2, "capped": True} and r[1]["on_hand"] is True, r
    assert planner_moods.mood_journal(s, m) == []                  # once a day
    s["date"]["tick"] = int(s["date"].get("tick") or 0) + TICKS_PER_DAY
    assert len(planner_moods.mood_journal(s, m)) == 1
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    assert 'for e in mood_journal(state, memory):' in src and '"kind": "mood"' in src


@test("E: stone the dwarf holds, or a search cut short, is not 'no loose stone'; out of reach is not 'none'")
def _():
    def asks(a):
        s = fort()
        s["moods"] = {"list": [mood([{"index": 0, "item": "BOULDER", "quantity": 1, "flags": ["hard"],
                                      "avail": a}], mood="Possessed", name="Zasit")]}
        m = Memory()
        m.moods_seen = {"5": abs_tick(s)}
        return [n for n in plan(s, m)[1] if n.startswith(NEEDS) and "Zasit" in n]
    assert asks(av(held=1)) == []
    assert asks(av(capped=True)) == []
    far = asks(av(free=5, reach=0))
    assert len(far) == 1 and "can't walk" in far[0] and "no loose stone" not in far[0], far
    none = asks(av())
    assert len(none) == 1 and "no loose stone of the kind it wants" in none[0], none
    assert mood_on_hand({"quantity": 1, "avail": av(held=1)}) is True
    assert mood_on_hand({"quantity": 2, "avail": av(held=1)}) is False


# the stub world of tests/test_moods.py, with a holder for carried items and a list that errors
_FAKE = re.search(r'FAKE = r"""(.*?)"""', (ROOT / "tests" / "test_moods.py").read_text(encoding="utf-8"),
                  re.S).group(1)


@test("lua: request_avail counts what the dwarf carries as held (not twice); an error part way is 'capped'")
def _():
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    W = L.execute(_FAKE, module_src("ai-moods.lua"))
    env = W.env
    W.reset()
    L.execute("local W = ...; W.env.dfhack.items.getHolderUnit = function(it) return it.holder end", W)
    j = W.job(L.table_from([L.table_from({"t": 4, "kind": "iron", "q": 1})]), L.table_from([]))
    u = W.unit(7, j)
    it = W.item(4, "iron", 1, L.table_from({}), 1)
    it.holder = u
    e = env.requests_missing(j)[1]
    a = env.request_avail(j.job_items[0], e, u)
    assert a.held == 1 and a.free == 0 and a.reach == 0 and a.enough, dict(a)
    it.holder = None
    a = env.request_avail(j.job_items[0], e, u)
    assert a.held == 0 and a.reach == 1 and not a.capped, dict(a)
    # an error part way: the search is cut short
    L.execute("local W = ...; W.env.dfhack.job.isSuitableItem = function() error('boom') end", W)
    W.reset()
    W.item(4, "iron", 200, L.table_from({}), 1)
    L.execute("local W = ...; W.env.dfhack.items.getPosition = function() error('boom') end", W)
    L.execute("""local W = ...
      local other = W.env.df.global.world.items.other
      setmetatable(other.BAR, {__index = function(_, k) if k == 0 then error('bad list') end end})
      other.BAR[0] = nil""", W)
    a = env.request_avail(j.job_items[0], e, u)
    assert a.capped, dict(a)


@test("lua: the changed files compile under Lua 5.3")
def _():
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime()
    for f in ("ai-moods.lua", "ai-bridge-actions.lua"):
        ok, err = L.eval("function(s, n) local f, e = load(s, n); return f ~= nil, e end")(
            (ROOT / "lua" / f).read_text(encoding="utf-8"), f)
        assert ok, (f, err)


@test("death line: the dead dwarf's own berserk mood is said as theirs; the killer's stays 'the killer ...'")
def _():
    import overseer
    ev = {"name": 'Amost Lertethzaneg "Tanglerelics", Stonecrafter', "cause": "STRUCK_DOWN",
          "killer": 'Udil Kobelcog "Summitboot", captain of the guard', "killer_kind": "citizen",
          "mood": "Berserk", "x": 1, "y": 2, "z": 3}
    w = overseer.death_words(ev)
    assert "(Amost Lertethzaneg was berserk after a failed mood)" in w, w
    assert "in a berserk mood" not in w, w
    ev2 = dict(ev, mood=None, killer_mood="Berserk")
    w2 = overseer.death_words(ev2)
    assert "the killer berserk" in w2 and "failed mood" not in w2, w2
    assert overseer.death_words({"name": "Ast", "cause": "THIRST", "mood": "Melancholy"}) == \
        "Ast, thirst, in a melancholy mood"


if __name__ == "__main__":
    finish()
