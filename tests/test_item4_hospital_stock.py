"""(0.105.112 item4) The hospitals' standing thread and cloth cap.

B (24 Nov): four hospital locations each wanting DF's 5 thread and 5 cloth
held 17 of the fort's 19 plant threads; item2's hospital_release lowered the
quotas only while a mood waited and put them back after. Now the hospitals
keep `hospital_stock_base` + `hospital_stock_per_patient` per patient waiting
for sutures or dressings (at most `hospital_stock_max`), all on the hospital
with the most chests, 0 on the rest, the surplus set out beside them; the
hold's restore never puts back more than the cap.

    python tests/test_item4_hospital_stock.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402

import planner_hospital_stock as HS  # noqa: E402
import hold_classes as H  # noqa: E402
import overseer  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG  # noqa: E402
from planner_core import COOLDOWN_KEYS  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"


def hosp(i, chests=2, thread=75000, cloth=50000):
    return {"id": i, "type": "HOSPITAL", "chests": chests, "want": {"thread": thread, "cloth": cloth},
            "have": {"thread": thread, "cloth": cloth}}


def fort(locs=None, items_thread=23, items_cloth=25, stitch=0) -> dict:
    s = copy.deepcopy(BASE)
    s["locations"] = {"count": {"HOSPITAL": 4}, "list": locs if locs is not None else
                      [hosp(3), hosp(12), hosp(13, chests=3), hosp(14)]}
    s.setdefault("supplies", {})
    s["supplies"]["hospital"] = {"thread": items_thread, "cloth": items_cloth}
    s["health"] = {"patients": [], "waiting": stitch, "stitch_wait": stitch}
    s["mood_help"] = {"cancels": []}
    return s


def rule(s):
    props, notes = [], []
    HS.hospital_stock_rule(s, Memory(), CFG, props, notes)
    return props


@test("config: the cap's keys and defaults (2 base, 1 a patient, 5 at most, half a day)")
def _():
    assert CFG["hospital_stock_base"] == 2 and CFG["hospital_stock_per_patient"] == 1
    assert CFG["hospital_stock_max"] == 5 and CFG["hospital_stock_cooldown_ticks"] == 600
    assert COOLDOWN_KEYS["hospital_stock"] == "hospital_stock_cooldown_ticks"


@test("B's four hospitals at 5 and 5: all of the cap on the one with most chests, 0 on the rest, surplus set out")
def _():
    props = rule(fort())
    assert len(props) == 1, [p.action for p in props]
    a = props[0].action
    assert a["type"] == "hospital_cap"
    assert a["caps"] == [{"id": 13, "thread": 2, "cloth": 2}, {"id": 3, "thread": 0, "cloth": 0},
                         {"id": 12, "thread": 0, "cloth": 0}, {"id": 14, "thread": 0, "cloth": 0}], a["caps"]
    assert a["set_out"] == {"thread": 10, "cloth": 10} and a["seen"] == {"thread": 23, "cloth": 25}, a
    assert "2 thread and 2 cloth" in props[0].reason and "free" in props[0].reason, props[0].reason


@test("patients waiting for sutures raise the cap one each, never past the max")
def _():
    caps, t, c = HS.hospital_targets(fort(stitch=2), CFG)
    assert t == c == 4 and caps[0]["thread"] == 4
    caps, t, c = HS.hospital_targets(fort(stitch=9), CFG)
    assert t == c == 5


@test("at the cap already, stock within it: nothing proposed; a raise only from the AI's own last cap")
def _():
    s = fort(locs=[hosp(3, thread=30000, cloth=20000)], items_thread=2, items_cloth=1)
    assert rule(s) == []
    # a patient: the cap is 3; the player's 2 (no AI record) is left
    s["health"]["stitch_wait"] = 1
    assert rule(s) == []
    # the AI set 2 before: raised to 3
    s["mood_help"]["hospital_cap"] = {"list": [{"id": 3, "thread": 30000, "cloth": 20000}]}
    props = rule(s)
    assert len(props) == 1 and props[0].action["caps"] == [{"id": 3, "thread": 3, "cloth": 3}], props
    assert "set_out" not in props[0].action


@test("a stock that could not be set out is not asked for again until it changes")
def _():
    s = fort(locs=[hosp(3, thread=30000, cloth=20000)], items_thread=6, items_cloth=2)
    s["mood_help"]["hospital_cap"] = {"list": [{"id": 3, "thread": 30000, "cloth": 20000}],
                                      "tried": {"thread": 6, "cloth": 2, "moved": 0, "at": 5}}
    assert rule(s) == []
    s["supplies"]["hospital"]["thread"] = 7
    props = rule(s)
    assert props and props[0].action["set_out"] == {"thread": 5}, props[0].action


@test("while hospital_release holds a quota at 0: the value kept for the restore is lowered, not the live 0")
def _():
    s = fort(locs=[hosp(3, thread=0, cloth=50000)], items_thread=2, items_cloth=2)
    s["mood_help"]["hospital_hold"] = {"locations": 1, "at": 5, "list": [{"id": 3, "thread": 75000}]}
    props = rule(s)
    assert len(props) == 1, props
    assert "(after the mood)" in props[0].reason and "cloth 5 -> 2" in props[0].reason, props[0].reason
    s["mood_help"]["hospital_hold"]["list"][0]["thread"] = 30000
    s["locations"]["list"][0]["want"]["cloth"] = 20000
    assert rule(s) == []


@test("no hospital: nothing; the planner calls the rule")
def _():
    assert rule(fort(locs=[])) == []
    src = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    assert "_guard(hospital_stock_rule, s, memory, cfg, proposals, notes)" in src


@test("wiring: class, words, catalog, dry run, cache, sizes")
def _():
    assert H.RULE_CLASS["hospital_stock"] == H.SURVIVAL and H.ACTION_CLASS["hospital_cap"] == H.SURVIVAL
    w = overseer.short({"type": "hospital_cap", "caps": []})
    assert w == overseer.SHORT_WORDS["hospital_cap"] and "hospital" in w, w
    cat = (LUA / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
    assert "hospital_cap = function(a) return reqscript('ai-mood-help').act_hospital_cap(a, txt, a.dry_run == true) end," in cat
    assert "'hospital_cap'," in cat
    sec = (LUA / "ai-bridge-sections.lua").read_text(encoding="utf-8")
    assert "CACHE_INVALIDATES.hospital_cap = {'moods', 'locations'}" in sec
    for f in ("ai-mood-help.lua", "ai-bridge-catalog.lua", "ai-bridge-sections.lua"):
        assert len((LUA / f).read_bytes().replace(b"\r", b"")) < 60_000, f
    assert (ROOT / "brain" / "planner.py").stat().st_size < 92_000


# ---- Lua (lupa: these run on the PC) -----------------------------------------------------

# item2's Lua world (tests/test_item2_hospital_release.py WORLD), read from its text
# (importing that file would run its finish())
def _item2_world() -> str:
    import ast
    tree = ast.parse((ROOT / "tests" / "test_item2_hospital_release.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "WORLD":
            return node.value.value
    raise AssertionError("item2's WORLD not found")


def world():
    from lupa.lua53 import LuaRuntime
    from lua_modules_util import module_src
    L = LuaRuntime(unpack_returned_tuples=True)
    W = L.execute(_item2_world(), module_src("ai-mood-help.lua"))
    return L, W


def T(L, d):
    return L.table_from(d)


def in_zone(it) -> bool:
    return 0 <= it.x <= 5 and 0 <= it.y <= 5


@test("Lua: the cap lowers the quotas, keeps a record; the surplus thread set out (97% too), a short piece kept")
def _():
    need_lua()
    L, W = world()
    env = W.env
    a1 = W.item("THREAD", 1, "plant")
    a2 = W.item("THREAD", 2, "silk")
    short = W.item("THREAD", 3, "plant", T(L, {"dim": 4000}))
    snipped = W.item("THREAD", 8, "plant", T(L, {"dim": 14655}))     # B's: 97%, set out too
    caps = T(L, [T(L, {"id": 4, "thread": 2, "cloth": 2}), T(L, {"id": 5, "thread": 0, "cloth": 0})])
    # a dry run: counts, changes nothing
    r = env.act_hospital_cap(T(L, {"caps": caps, "set_out": T(L, {"thread": 3}), "dry_run": True}))
    assert r.ok and r.changed == 2 and r.thread_out == 3, dict(r)
    assert W.hosp.c.desired_thread == 150000 and a1.moved is None and len(list(W.site.keys())) == 0
    r = env.act_hospital_cap(T(L, {"caps": caps, "set_out": T(L, {"thread": 3}),
                                   "seen": T(L, {"thread": 3, "cloth": 0})}))
    assert r.ok and r.changed == 2 and r.thread_out == 3 and r.no_such_hospital == 1, dict(r)   # 5 is a temple
    assert W.hosp.c.desired_thread == 30000 and W.hosp.c.desired_cloth == 20000
    assert W.hosp.c.need_more.thread is False and W.temple.c.desired_thread == 5
    assert a1.moved is not None and a2.moved is not None and snipped.moved is not None and short.moved is None
    assert not in_zone(a1) and a1.flags.forbid is False
    rep = env.report().hospital_cap
    assert rep.list[1].id == 4 and rep.list[1].thread == 30000 and rep.tried.thread == 3 and rep.tried.moved == 3
    # again: at the cap, nothing to set out: refused, said
    r = env.act_hospital_cap(T(L, {"caps": caps, "set_out": T(L, {"thread": 1})}))
    assert not r.ok and r.rejected and "at the cap" in r.error, dict(r)


@test("Lua: a quota the player set below the cap stays; the AI's own last cap is raised")
def _():
    need_lua()
    L, W = world()
    env = W.env
    W.hosp.c.desired_thread = 15000
    r = env.act_hospital_cap(T(L, {"caps": T(L, [T(L, {"id": 4, "thread": 3, "cloth": 3})])}))
    assert r.ok and W.hosp.c.desired_thread == 15000 and W.hosp.c.desired_cloth == 30000, dict(r)
    r = env.act_hospital_cap(T(L, {"caps": T(L, [T(L, {"id": 4, "thread": 4, "cloth": 4})])}))
    assert r.ok and W.hosp.c.desired_cloth == 40000 and W.hosp.c.desired_thread == 15000, dict(r)


@test("Lua: while a mood's hold has the quota at 0, the cap lowers the kept value; the restore stops at the cap")
def _():
    need_lua()
    L, W = world()
    env = W.env
    W.item("THREAD", 1, "plant")
    assert env.act_hospital_release(T(L, {"thread": 1, "kind": "plant"})).ok
    assert W.hosp.c.desired_thread == 0
    r = env.act_hospital_cap(T(L, {"caps": T(L, [T(L, {"id": 4, "thread": 2, "cloth": 2})])}))
    assert r.ok and r.changed == 2, dict(r)
    assert W.hosp.c.desired_thread == 0 and W.hosp.c.desired_cloth == 20000       # held: still 0
    assert W.site["ai-overseer/hospital-hold"].locs[1].thread == 30000
    env = W.load()                                              # a reload
    r = env.act_hospital_release(T(L, {"restore": True}))
    assert r.ok and r.restored == 1 and W.hosp.c.desired_thread == 30000, dict(r)


@test("Lua: a restore after an old hold (kept 150000) never puts back more than the cap on record")
def _():
    need_lua()
    L, W = world()
    env = W.env
    W.item("THREAD", 1, "plant")
    assert env.act_hospital_release(T(L, {"thread": 1, "kind": "plant"})).ok
    W.site["ai-overseer/hospital-cap"] = T(L, {"caps": T(L, [T(L, {"id": 4, "thread": 45000, "cloth": 20000})])})
    r = env.act_hospital_release(T(L, {"restore": True}))
    assert r.ok and W.hosp.c.desired_thread == 45000, (dict(r), W.hosp.c.desired_thread)


@test("Lua: bad payloads refused")
def _():
    need_lua()
    L, W = world()
    r = W.env.act_hospital_cap(T(L, {}))
    assert not r.ok and r.rejected and "caps" in r.error


finish()
