"""(0.105.31 reserve fixes) An independent verifier's cases against the mood
reserves, each made a test:

- A, A2: the fibre plants aren't processed for thread while drink is short,
  nor when the brewable plants left (less the brew orders) fall to the drink
  line; B: no plot goes to a fibre crop while drink is short.
- C, C2: a noble's mandate (shoes, socks) is never held by a reserve.
- D: at the reserve line the reserve rule tops up a batch over it (it
  stopped at the line, and select() held the other orders there for good);
  an order is capped at what lies over the line; no order waits for good
  while the materials exist (a loop proves it). The flask rule falls back
  to glass while only the reserved leather is left.
- L1-L4 (lua set_farm_crops): a plot swapped back for drink isn't swapped
  to fibre in that season or the next; a thread swap that can do nothing
  says so (thread_none), and the brain waits for the next season.
- depot: when leaving the AI's halls out of the gates' scan starts leaves no
  start in the fort itself, the founding stair or meeting hall is the start
  (else the starts left out), never a pocket.
- renew_well_dig takes away only a dig or channel job; a mood's count over
  the catch-all item lists is taken again at most once a game hour.

    python tests/test_fix31_reserve_fixes.py
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402
from planner import PLANNER_CONFIG, Memory, plan, select, record  # noqa: E402
from planner_core import Proposal, TICKS_PER_YEAR  # noqa: E402
from planner_moods import _mood_reserve_rule, RESERVE_BATCH  # noqa: E402
from planner_army import _flask_rule  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG


def _const(path: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / path).read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


def base() -> dict:
    s = copy.deepcopy(BASE)
    su = s.setdefault("supplies", {})
    su.update({"cloth_kinds": {"plant": 0, "silk": 0, "yarn": 0}, "thread_kinds": {"plant": 0},
               "thread_plants": 0, "hides": 0})
    return s


def reserve(s, memory=None):
    props, notes = [], []
    _mood_reserve_rule(s, memory if memory is not None else Memory(), CFG, props, notes)
    return props, notes


def recipes(props):
    return [p.action.get("recipe") or p.action.get("type") for p in props]


def thirsty() -> dict:
    """A: drink 0 for 194, 3 brewable plants, all of them fibre plants."""
    s = base()
    s["stocks"]["drink"] = 0
    s["stocks"]["plants"] = 3
    s["supplies"].update({"brewable_plants": 3, "brewable_growths": 0, "thread_plants": 3})
    return s


# ---- 1. the reserve and the drink ------------------------------------------------------

@test("fix 1 (A): drink 0, 3 brewable fibre plants: not processed for thread (by the rule or plan); the drink brews them")
def _():
    s = thirsty()
    props, notes = reserve(s)
    assert "process_plants" not in recipes(props), props
    assert any("drink is short" in n for n in notes), notes
    ps, _ = plan(copy.deepcopy(s), Memory())
    assert not [p for p in ps if p.rule == "mood_reserve" and p.action.get("recipe") == "process_plants"]
    assert [p for p in ps if p.rule == "drink" and p.action.get("recipe") == "brew_drink"]


@test("fix 1 (A2): a brew order queued for the plants: still not processed; drink fine but the plants left at the line: not")
def _():
    s = thirsty()
    s["orders"] = [{"recipe": "brew_drink", "by_ai": True, "amount_total": 3, "amount_left": 3}]
    assert "process_plants" not in recipes(reserve(s)[0])
    s = base()                                         # drink plenty (3929 for 194)
    s["supplies"].update({"brewable_plants": 200, "thread_plants": 3, "thread_brewable_plants": 3})
    s["orders"] = [{"recipe": "brew_drink", "by_ai": True, "amount_total": 10, "amount_left": 10}]
    assert "process_plants" not in recipes(reserve(s)[0])        # 200 - 10 - 3 = 187 <= 194
    s["supplies"]["brewable_plants"] = 400
    assert "process_plants" in recipes(reserve(s)[0])            # 387 left: spare
    s["supplies"].update({"brewable_plants": 5, "thread_brewable_plants": 0})
    assert "process_plants" in recipes(reserve(s)[0])            # hemp: the drink's plants untouched
    s["supplies"].pop("thread_brewable_plants")                  # an older bridge: all counted brewable
    assert "process_plants" not in recipes(reserve(s)[0])


def fibre_farm(s):
    s["farms"] = {"crops": {"MUSHROOM_HELMET_PLUMP": {"name": "plump helmet", "seeds": 20, "planted": 1, "brews": "x"},
                            "HEMP": {"name": "hemp", "seeds": 10, "planted": 0, "thread": True}},
                  "plot_list": [{"id": 1, "ok_now": True, "options": 2}], "plots": 1}
    return s


@test("fix 1 (B): no plot swapped to a fibre crop while drink is short; swapped once drink is fine")
def _():
    s = fibre_farm(base())
    s["stocks"]["drink"] = 0
    m = Memory()
    m.farm_steer = "crops"
    props, notes = reserve(s, m)
    assert not [p for p in props if p.action.get("type") == "set_farm_crops"], props
    assert any("while drink is short" in n for n in notes), notes
    s["stocks"]["drink"] = 3000
    props, _ = reserve(s, Memory())
    assert [p.action for p in props] == [{"type": "set_farm_crops", "thread": True, "drink": False}], props


# ---- 2. the holds at the line ------------------------------------------------------------

def run_select(s, props):
    allowed, held = select(props, s, Memory())
    return allowed, held


@test("fix 2 (C, C2): a noble's mandate for shoes or socks is never held by a reserve")
def _():
    s = base()
    s["supplies"]["cloth_kinds"]["plant"] = 50
    s["stocks"]["leather"] = 2
    s["mandates"] = [{"kind": "Make", "item": "SHOES", "remaining": 2, "days_left": 30}]
    ps, _ = plan(copy.deepcopy(s), Memory())
    mand = [p for p in ps if p.rule == "mandate"]
    assert mand and mand[0].action["recipe"] == "leather_shoes", ps
    allowed, held = run_select(s, mand)
    assert allowed and allowed[0].action["amount"] == 2, held
    s["supplies"]["cloth_kinds"]["plant"] = 3
    s["stocks"]["leather"], s["stocks"]["cloth"] = 0, 3
    s["mandates"] = [{"kind": "Make", "item": "SHOES", "remaining": 1, "subtype": "ITEM_SHOES_SOCKS", "days_left": 30}]
    ps, _ = plan(copy.deepcopy(s), Memory())
    mand = [p for p in ps if p.rule == "mandate"]
    assert mand and mand[0].action["recipe"] == "cloth_socks", ps
    assert run_select(s, mand)[0]


def quiver(n):
    return Proposal("quivers_order", {"type": "work_order", "recipe": "leather_quiver", "amount": n}, "q", 4, True)


@test("fix 2 (D): at the line with hides the reserve tans a batch over it; an order held at the line, capped over it")
def _():
    s = base()
    s["supplies"]["cloth_kinds"]["plant"] = 50
    s["stocks"]["leather"], s["supplies"]["hides"] = 2, 10
    props, _ = reserve(s)
    assert [p.action for p in props] == [{"type": "work_order", "recipe": "tan_hide", "amount": RESERVE_BATCH}], props
    allowed, held = run_select(s, [quiver(2)])
    assert not allowed and any("kept for strange moods" in h for h in held), held
    s["stocks"]["leather"] = 5
    allowed, _ = run_select(s, [quiver(5)])
    assert allowed and allowed[0].action["amount"] == 3, allowed          # 5 - the 2 kept
    assert "at most 3" in allowed[0].reason
    s["stocks"]["leather"] = 3
    assert not reserve(s)[0]                                             # over the line: nothing to top up
    s["supplies"]["hides"] = 0
    s["stocks"]["leather"] = 2
    assert not reserve(s)[0]                                             # nothing to tan: held (the reserve's point)


def simulate(s, consumer, take, make_key, use_key, need, cycles=40):
    """Cycles of the reserve rule and select(): a made order adds its amount
    of the material (taking `make_key`), a consumer order takes its amount.
    Returns (made by the consumer, lowest stock seen)."""
    made, low = 0, None
    for _ in range(cycles):
        if made >= need:
            break
        props, _ = reserve(s)
        p = consumer(need - made)
        allowed, _ = run_select(s, props + [p])
        for a in allowed:
            n = a.action["amount"]
            if a.rule == "mood_reserve":
                src = make_key(s)
                n = min(n, src[0][src[1]])
                src[0][src[1]] -= n
                take(s, +n)
            else:
                take(s, -n)
                made += n
        cur = use_key(s)
        low = cur if low is None else min(low, cur)
    return made, low


@test("fix 2: no order waits for good while the material can be made: quivers from hides, bags from plant thread")
def _():
    s = base()
    s["supplies"]["cloth_kinds"]["plant"] = 50
    s["stocks"]["leather"], s["supplies"]["hides"] = 2, 30

    def leather(st, d):
        st["stocks"]["leather"] += d
    made, low = simulate(s, quiver, leather, lambda st: (st["supplies"], "hides"),
                         lambda st: st["stocks"]["leather"], need=6)
    assert made == 6 and low >= CFG["reserve_leather"], (made, low)

    s = base()
    s["supplies"]["cloth_kinds"]["plant"] = 3
    s["supplies"]["thread_kinds"]["plant"] = 30

    def cloth(st, d):
        st["supplies"]["cloth_kinds"]["plant"] += d

    def bag(n):
        return Proposal("bags", {"type": "work_order", "recipe": "cloth_bag", "amount": n}, "bags", 5, True)
    made, low = simulate(s, bag, cloth, lambda st: (st["supplies"]["thread_kinds"], "plant"),
                         lambda st: st["supplies"]["cloth_kinds"]["plant"], need=5)
    assert made == 5 and low >= CFG["reserve_plant_cloth"], (made, low)


@test("fix 2 (flask): leather at or under the reserve -> glass vials; over it -> waterskins of the spare leather only")
def _():
    got = {}
    for leather in (0, 2, 3, 6):
        s = copy.deepcopy(BASE)
        s["stocks"]["leather"] = leather
        s.setdefault("military", {})["gear"] = {"flask_places": 10, "flasks_assigned": 0, "flasks_free": 0}
        s["supplies"].update({"sand_bags": 20, "fuel": 20, "hides": 0})
        s["orders"] = []
        ps, n = [], []
        _flask_rule(s, Memory(), CFG, ps, n)
        allowed, held = select(ps, s, Memory())
        assert len(allowed) == len(ps) == 1, held
        got[leather] = (allowed[0].action["recipe"], allowed[0].action["amount"])
    assert got[0][0] == got[2][0] == "glass_vial", got
    assert got[3] == ("leather_waterskin", 1) and got[6] == ("leather_waterskin", 4), got


# ---- 3. a fibre swap that does nothing ----------------------------------------------------------

@test("fix 3: the fibre swap that changed nothing (thread_none) waits for the next season")
def _():
    s = fibre_farm(base())
    m = Memory()
    p = reserve(s, m)[0][0]
    assert p.action["type"] == "set_farm_crops"
    record([(p, {"ok": True, "changed": 0, "thread_none": True, "reason": "no fibre crop..."})], s, m)
    assert m.reserve_swap_off is not None
    assert not [q for q in reserve(s, m)[0] if q.action.get("type") == "set_farm_crops"]
    s2 = copy.deepcopy(s)
    s2["date"]["tick"] += TICKS_PER_YEAR // 4
    if s2["date"]["tick"] >= TICKS_PER_YEAR:
        s2["date"]["tick"] -= TICKS_PER_YEAR
        s2["date"]["year"] += 1
    assert [q for q in reserve(s2, m)[0] if q.action.get("type") == "set_farm_crops"]
    # a swap that did something: no wait
    m2 = Memory()
    record([(p, {"ok": True, "changed": 1})], s, m2)
    assert m2.reserve_swap_off is None


@test("fix 3: the bridge reports the brewable thread plants")
def _():
    src = (ROOT / "lua" / "ai-bridge-report.lua").read_text(encoding="utf-8")
    assert "out.thread_brewable_plants = out.thread_brewable_plants + n" in src


if LuaRuntime is not None:
    def farms():
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().LUA_DIR = str(ROOT / "lua")
        B, W = lua.execute(_const("test_builder.py", "HARNESS"),
                           (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8"),
                           (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8"))
        FF = lua.execute(_const("test_builder.py", "FARM_FAKE"), B)
        return lua, B, FF

    def T(lua, d):
        return lua.table_from(d)

    def setup(lua, FF, seeds, plots):
        return FF.setup(T(lua, [T(lua, x) for x in seeds]), T(lua, [T(lua, x) for x in plots]))

    @test("fix 1 (L1): a plot swapped back for drink isn't swapped to fibre again that season or the next")
    def _():
        lua, B, FF = farms()
        plots = setup(lua, FF, [[5, 40], [7, 20]], [[41, False, 0]])
        s = B.current_season()
        B.set_farm_crops(T(lua, {}), False)
        assert plots[1].plant_id[s] == 5                              # prickle berry (brews)
        r = B.set_farm_crops(T(lua, {"thread": True, "drink": False}), False)
        assert plots[1].plant_id[s] == 7 and r.changed > 0            # hemp: one fibre plot
        r = B.set_farm_crops(T(lua, {"drink": True, "thread": True}), False)
        assert plots[1].plant_id[s] == 5                              # back for drink
        r = B.set_farm_crops(T(lua, {"thread": True, "drink": False}), False)
        assert plots[1].plant_id[s] == 5 and r.changed == 0, dict(r)  # no swap back: the drink's
        assert r.thread_none and "kept for drink" in r.reason
        r = B.set_farm_crops(T(lua, {"drink": True}), False)
        assert plots[1].plant_id[s] == 5 and r.changed == 0
        # two seasons on, the thread swap may take it again
        lua.execute("df.global.cur_year = (df.global.cur_year or 0) + 1")
        r = B.set_farm_crops(T(lua, {"thread": True, "drink": False}), False)
        assert plots[1].plant_id[s] == 7, dict(r)

    @test("fix 1 (L2): a crop the player set is kept; a fallow plot still gets the fibre crop")
    def _():
        lua, B, FF = farms()
        plots = setup(lua, FF, [[5, 40], [7, 20]], [[51, False, 0], [52, False, 10]])
        s = B.current_season()
        plots[1].plant_id[s] = 5
        r = B.set_farm_crops(T(lua, {"thread": True, "drink": False}), False)
        assert plots[1].plant_id[s] == 5 and plots[2].plant_id[s] == 7 and not r.thread_none

    @test("fix 3 (L3, L4): fibre seeds that grow on no plot: changed 0 with a reason (thread_none); no fibre seed: none picked")
    def _():
        lua, B, FF = farms()
        plots = setup(lua, FF, [[1, 40], [7, 20]], [[61, True, 0]])
        s = B.current_season()
        B.set_farm_crops(T(lua, {}), False)
        r = B.set_farm_crops(T(lua, {"thread": True, "drink": False}), False)
        assert r.ok and r.changed == 0 and r.thread_none and "no fibre crop" in r.reason, dict(r)
        assert plots[1].plant_id[s] == 1
        lua, B, FF = farms()
        plots = setup(lua, FF, [[1, 40]], [[71, True, 0]])
        s = B.current_season()
        B.set_farm_crops(T(lua, {}), False)
        r = B.set_farm_crops(T(lua, {"thread": True}), False)
        assert plots[1].plant_id[s] == 1 and r.thread_none
        r = B.set_farm_crops(T(lua, {}), False)                      # no thread asked: nothing said
        assert not r.thread_none

    # ---- 4. the depot scan ---------------------------------------------------------------

    def depot_world():
        sys.argv = sys.argv[:1]
        import importlib.util
        spec = importlib.util.spec_from_file_location("depotscan", ROOT / "tests" / "test_fix31_depotscan.py")
        t = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(t)
        lua, M, W = t.gates()
        width = 60
        rows = ["#" * width]
        for y in range(1, 10):
            rows.append("#" + "." * 18 + ("." if y == 5 else "#") + "." * 9 + "#" * 5
                        + (".." if y in (2, 3) else "##") + "#" * (width - 37))
        rows.append("#" * width)
        t.set_map(lua, W, rows, width)
        return t, lua, M, W

    def pts(lua, xs):
        return lua.table_from([lua.table_from({"x": x, "y": y, "z": 0}) for x, y in xs])

    def starts_of(M, starts):
        return sorted((p.x, p.y) for p in M.fort_starts(starts).values())

    @test("fix 4: the one citizen of the main area in the depot hall, another in a pocket: the founding stair, not the pocket")
    def _():
        t, lua, M, W = depot_world()
        t.with_builder(lua, M, t.deep_record(lua))
        lua.execute("local M = ...; M.fort_anchor_starts = function() return {{x = 5, y = 5, z = 0}} end", M)
        assert starts_of(M, pts(lua, [(24, 5), (35, 2)])) == [(5, 5)]
        # no stair or meeting hall: the hall's citizen after all (it stands somewhere big), not the pocket
        lua.execute("local M = ...; M.fort_anchor_starts = function() return {} end", M)
        assert starts_of(M, pts(lua, [(24, 5), (35, 2)])) == [(24, 5)]
        # a citizen in the fort proper: as before
        assert starts_of(M, pts(lua, [(24, 5), (5, 5)])) == [(5, 5)]
        # the only citizen a pocket's, nobody left out: the pocket (a new fort's first room)
        assert starts_of(M, pts(lua, [(35, 2)])) == [(35, 2)]

    @test("fix 4: the 0.105.30 keep exclusion the same: a citizen in the keep, another in a pocket -> the meeting hall")
    def _():
        t, lua, M, W = depot_world()
        lua.execute("""local M = ...
          M.reqscript = function(name)
              return {deep_depot_data = function() return nil end, halls_data = function() return nil end,
                      keep_data = function() return {x = 24, y = 5, z = 0, r = 4} end}
          end
          M.fort_anchor_starts = function() return {{x = 10, y = 3, z = 0}} end""", M)
        assert starts_of(M, pts(lua, [(24, 5), (35, 3)])) == [(10, 3)]

    # ---- 5. renew_well_dig ---------------------------------------------------------------

    @test("fix 5: renew_well_dig takes away only the channel or dig job on the well's tile")
    def _():
        wells = sys.modules.get("_wells_boot")
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().LUA_DIR = str(ROOT / "lua")
        B, W = lua.execute(_const("test_builder.py", "HARNESS"),
                           (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8"),
                           (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8"))
        lua.execute("df = {global = {cur_year = 148, cur_year_tick = 100}}")
        W.reset()
        B.well_miners = lambda: W.citizens
        for k in range(1, 3):
            W.set(70, 58, 71 - k, lua.table_from({"shape": "EMPTY"}))
        W.set(70, 58, 68, lua.table_from({"shape": "EMPTY", "liquid": True, "depth": 7}))
        r = B.place_well(lua.table(), lua.table_from({"year": 148, "tick": 100}), False)
        assert r.ok, r.error
        lua.execute("""
          df.job_type = {[0] = 'Dig', [1] = 'DigChannel', [2] = 'ConstructBuilding', [3] = 'StoreItemInStockpile'}
          local function job(t, x) return {job_type = t, pos = {x = x, y = 58, z = 71}} end
          local jobs = {job(1, 70), job(2, 70), job(3, 70), job(1, 71), job(0, 70)}
          local link = nil
          for i = #jobs, 1, -1 do link = {item = jobs[i], next = link} end
          df.global.world = {jobs = {list = {next = link}}}
          REMOVED = {}
          dfhack.job = {getWorker = function(j) return nil end,
                        removeJob = function(j) table.insert(REMOVED, j.job_type) return true end}
        """)
        got = B.renew_well_dig(r.project_id, 2, False)
        assert got.ok and got.renewed == 2, dict(got)
        removed = sorted(lua.globals().REMOVED.values())
        assert removed == [0, 1], removed                     # the dig and the channel, not the build or haul
        assert B.well_dig_job(lua.table_from({"job_type": 1})) and not B.well_dig_job(lua.table_from({"job_type": 2}))

    # ---- 6. the mood's count -------------------------------------------------------------

    @test("fix 6: a request over IN_PLAY isn't counted again for items coming and going within the hour; after it, it is")
    def _():
        lua = LuaRuntime(unpack_returned_tuples=True)
        W = lua.execute(_const("test_moods.py", "FAKE"), module_src("ai-moods.lua"))
        M = W.env
        reqs = lua.table_from([lua.table_from({"t": -1, "q": 3})])           # any item: the IN_PLAY list
        j = W.job(reqs, lua.table())
        u = W.unit(3, j)
        W.item(1, 1, 150)                                                   # out of walk
        a0 = M.mood_report(j, u)[1].avail
        assert a0.reach == 0 and not a0.enough, dict(a0)
        W.item(1, 1, 1)                                                     # IN_PLAY grew
        assert M.mood_report(j, u)[1].avail.reach == 0                      # kept: within the hour
        lua.execute("local W = ...; W.env.df.global.cur_year_tick = W.env.df.global.cur_year_tick + 50", W)
        assert M.mood_report(j, u)[1].avail.reach == 1                      # an hour on: counted again
        # a request of its own kind (CLOTH): at once, as 0.105.31
        reqs = lua.table_from([lua.table_from({"t": 1, "kind": 1, "q": 3})])
        j2 = W.job(reqs, lua.table())
        u2 = W.unit(4, j2)
        n0 = M.mood_report(j2, u2)[1].avail.reach
        W.item(1, 1, 1)
        assert M.mood_report(j2, u2)[1].avail.reach == n0 + 1


if __name__ == "__main__":
    sys.exit(finish())
