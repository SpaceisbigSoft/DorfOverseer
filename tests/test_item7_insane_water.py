"""(item7, the player's "Bring water to them", 26 Nov) Water and food for the
insane: D lost 12 melancholy and raving dwarves to thirst overnight, and DF
lets no insane dwarf drink or eat. lua/ai-insane.lua water() sets a
melancholy or raving dwarf's thirst / hunger timer back to 0 (DFHack's
full-heal way) once it nears dehydration / starvation, never a berserk,
catatonic or sane one; the `insane` section says each row's thirst and
hunger and the AI's tries; the bridge's insane_water action; the brain
(brain/planner_insane.py) proposes it with a plain reason line, says the
state in the note, and is switched off with insane_water False; the thirst
rule's words for the insane say so.

    python tests/test_item7_insane_water.py
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
import planner_insane as PI  # noqa: E402
import planner_thirst as PT  # noqa: E402
from digest import normalize  # noqa: E402
from planner_core import EMERGENCY, LIMIT_EXEMPT, NO_COOLDOWN  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None


def _fake() -> str:
    """The fake fort of test_r41_insane.py (its FAKE string), read from its text."""
    tree = ast.parse((ROOT / "tests" / "test_r41_insane.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "FAKE" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("no FAKE in test_r41_insane.py")


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(_fake(), module_src("ai-insane.lua"))
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


def dwarf(lua, w, uid, mood, thirst, hunger, **kw):
    t = {"id": uid, "name": f"Urist{uid}", "mood": w.MOOD[mood] if mood else -1, "own": True,
         "pos": {"x": 50 + uid, "y": 50, "z": 100}, "counters2": {"thirst_timer": thirst, "hunger_timer": hunger}}
    t.update(kw)
    return w.unit(T(lua, t))


def water(lua, env, units=None, dry=False):
    o = T(lua, {"units": units}) if units is not None else T(lua, {})
    return py(env.water(o, dry))


# --- the bridge: water() --------------------------------------------------------------------


@test("water: a melancholy dwarf past 40000 thirst is set back to 0, a raving one past 65000 hunger fed; "
      "only the due timer is touched; the try is recorded")
def _():
    need_lua()
    lua, env, w = world()
    a = dwarf(lua, w, 1, "Melancholy", 45000, 1000)
    b = dwarf(lua, w, 2, "Raving", 100, 70000)
    out = water(lua, env, [1, 2])
    assert out["ok"] and out["watered"] == 1 and out["fed"] == 1, out
    assert a.counters2.thirst_timer == 0 and a.counters2.hunger_timer == 1000
    assert b.counters2.thirst_timer == 100 and b.counters2.hunger_timer == 0
    assert "full-heal" in out["how"], out
    rec = py(env.state().water)
    assert rec["1"]["n"] == 1 and rec["1"]["thirst"] == 45000 and rec["2"]["hunger"] == 70000, rec


@test("water: never a berserk, catatonic or sane dwarf, nor one short of the bars, nor one not the fort's; "
      "each skipped with why")
def _():
    need_lua()
    lua, env, w = world()
    ber = dwarf(lua, w, 1, "Berserk", 60000, 90000)
    cat = dwarf(lua, w, 2, "Traumatized", 60000, 90000)
    sane = dwarf(lua, w, 3, None, 60000, 90000)
    low = dwarf(lua, w, 4, "Melancholy", 39999, 64999)
    other = dwarf(lua, w, 5, "Raving", 60000, 90000, own=False, civ_id=99)
    dead = dwarf(lua, w, 6, "Raving", 60000, 90000, dead=True)
    out = water(lua, env, [1, 2, 3, 4, 5, 6])
    assert out["watered"] == 0 and out["fed"] == 0 and not out["units"], out
    why = {s["id"]: s["why"] for s in out["skipped"]}
    assert "berserk" in why[1] and "catatonic" in why[2] and "not due" in why[4], why
    assert all("living insane" in why[i] for i in (3, 5, 6)), why
    for u in (ber, cat, sane, low, other, dead):
        assert u.counters2.thirst_timer in (60000, 39999), u.id


@test("water: a dry run names who is due and sets no timer; nil units sees to every melancholy and raving one, "
      "past the report's 10-row cap")
def _():
    need_lua()
    lua, env, w = world()
    us = [dwarf(lua, w, i, "Melancholy" if i % 2 else "Raving", 50000, 0) for i in range(1, 13)]
    out = water(lua, env, None, dry=True)
    assert out["dry_run"] and out["watered"] == 12, out
    assert all(u.counters2.thirst_timer == 50000 for u in us)
    assert py(env.state().water) in ({}, None), py(env.state().water)
    out = water(lua, env)
    assert out["watered"] == 12 and all(u.counters2.thirst_timer == 0 for u in us), out


@test("report: each insane row has its thirst and hunger, dehydrated / starving, water_due (melancholy and raving "
      "only) and the AI's tries; the section gives the bars")
def _():
    need_lua()
    lua, env, w = world()
    dwarf(lua, w, 1, "Melancholy", 52000, 80000)
    dwarf(lua, w, 2, "Berserk", 52000, 80000)
    dwarf(lua, w, 3, "Raving", 1000, 2000)
    rep = py(env.report())
    rows = {r["id"]: r for r in rep["list"]}
    r1 = rows[1]
    assert (r1["thirst"], r1["hunger"], r1.get("dehydrated"), r1.get("starving"), r1.get("water_due")) == \
        (52000, 80000, True, True, True), r1
    assert rows[2].get("water_due") is None and rows[2]["thirst"] == 52000, rows[2]
    assert rows[3].get("water_due") is None and rows[3].get("dehydrated") is None, rows[3]
    assert rep["water_thirst"] == 40000 and rep["water_hunger"] == 65000, rep
    water(lua, env, [1])
    r1 = {r["id"]: r for r in py(env.report())["list"]}[1]
    assert r1["thirst"] == 0 and r1["watered"] == 1 and isinstance(r1["watered_at"], int), r1
    assert r1.get("water_due") is None


@test("report: a fort with more than ten insane: the due past the listed rows come in water_more")
def _():
    need_lua()
    lua, env, w = world()
    for i in range(1, 14):
        dwarf(lua, w, i, "Raving", 41000 if i > 3 else 0, 0)
    rep = py(env.report())
    assert len(rep["list"]) == 10, len(rep["list"])
    more = rep["water_more"]
    assert [m["id"] for m in more] == [11, 12, 13] and all(m["water_due"] for m in more), more


@test("bridge: insane_water is an action with a dry run; its validator wants a list of ids and asks ai-insane.water")
def _():
    cat = (ROOT / "lua" / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
    i = cat.index("    insane_water = function(a)")
    body = cat[i:cat.index("\n    end,", i)]
    assert "reject('insane_water: units is a list of unit ids')" in body and "math.tointeger" in body
    assert "reqscript('ai-insane').water({units = ids}, a.dry_run == true)" in body, body
    assert "'insane_water',   -- (item7)" in cat
    assert "insane_water =" not in cat.split("RELEASE_WHILE_HALTED = {")[1].split("}")[0], "runs while halted"
    if LuaRuntime is None:
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    fn = body.replace("insane_water = function(a)", "return function(a)", 1) + "\nend"
    calls = []
    lua.globals().reject = lambda m: lua.table_from({"ok": False, "error": m})
    lua.globals().reqscript = lambda name: lua.table_from(
        {"water": lambda o, dry: calls.append((name, py(o), dry)) or lua.table_from({"ok": True})})
    f = lua.execute(fn)
    assert py(f(lua.table_from({"units": 5})))["ok"] is False
    assert py(f(lua.table_from({"units": lua.table_from(["x"])})))["ok"] is False
    assert py(f(lua.table_from({"units": lua.table_from([])})))["ok"] is False
    assert py(f(lua.table_from({"units": lua.table_from([7, 8]), "dry_run": True})))["ok"] is True
    assert calls == [("ai-insane", {"units": [7, 8]}, True)], calls


@test("compile: the changed Lua files load (texlua or lupa)")
def _():
    import shutil
    import subprocess
    files = [ROOT / "lua" / "ai-insane.lua", ROOT / "lua" / "ai-bridge-catalog.lua"]
    if LuaRuntime is not None:
        lua = LuaRuntime(unpack_returned_tuples=True)
        for f in files:
            assert lua.eval("load")(f.read_text(encoding="utf-8")) is not None, f
        return
    tex = shutil.which("texlua")
    if not tex:
        need_lua()
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        chk = Path(tmp) / "chk.lua"
        chk.write_text("assert(loadfile(arg[1]))\n", encoding="utf-8")
        for f in files:
            r = subprocess.run([tex, str(chk), str(f)], capture_output=True, text=True)
            assert r.returncode == 0, (f, r.stdout, r.stderr)


# --- the brain -------------------------------------------------------------------------------


def state(insane, **extra):
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    base["insane"] = insane
    base.update(extra)
    return normalize(base)


def run_rule(s, **cfg):
    props, notes = [], []
    PI._insane_rule(s, dict(PLANNER_CONFIG, **cfg), props, notes, Memory())
    return props, notes


def row(uid, kind, thirst, hunger, **kw):
    r = {"id": uid, "name": f"Urist{uid}", "kind": kind, "hazards": {}, "doors": 0, "locked": 0,
         "thirst": thirst, "hunger": hunger}
    r.update(kw)
    return r


@test("brain: a melancholy dwarf at thirst 41000: insane_water proposed (an emergency rule), the reason line says "
      "plainly it is a direct DFHack change the player can turn off")
def _():
    s = state({"list": [row(7, "melancholy", 41000, 100)], "locks": 0, "water_thirst": 40000, "water_hunger": 65000})
    props, notes = run_rule(s)
    w = [p for p in props if p.rule == "insane_water"]
    assert len(w) == 1 and w[0].action == {"type": "insane_water", "units": [7]}, props
    why = w[0].reason
    for bit in ("Urist7 (melancholy, thirst 41000", "DF lets no insane dwarf drink or eat", "directly through DFHack",
                "full-heal", "insane_water False", "never a berserk, catatonic or sane dwarf"):
        assert bit in why, (bit, why)
    assert "insane_water" in EMERGENCY and "insane_water" in NO_COOLDOWN and "insane_water" in LIMIT_EXEMPT
    n = notes[0]
    assert "thirst 41000" in n and "hunger 100" in n and "sets their thirst back to 0 directly through DFHack" in n, n
    assert "nothing more can be done" not in n, n


@test("brain: not due (short of the bars, or the bridge's own bars higher), berserk / catatonic: no insane_water")
def _():
    s = state({"list": [row(1, "melancholy", 39000, 64000), row(2, "berserk", 70000, 90000),
                        row(3, "catatonic", 70000, 90000)], "locks": 0})
    props, _ = run_rule(s)
    assert not [p for p in props if p.rule == "insane_water"], props
    # settings below the bridge's floor: the bridge's bars hold
    s = state({"list": [row(1, "raving", 30000, 0)], "locks": 0, "water_thirst": 40000, "water_hunger": 65000})
    props, _ = run_rule(s, insane_water_thirst=20000)
    assert not [p for p in props if p.rule == "insane_water"], props
    # hunger alone is enough
    s = state({"list": [row(1, "raving", 0, 66000)], "locks": 0})
    props, _ = run_rule(s)
    assert [p.action["units"] for p in props if p.rule == "insane_water"] == [[1]], props


@test("brain: a try lately (still due: it did not take) waits for the retry, and the failure is said")
def _():
    s = state({"list": [row(1, "melancholy", 45000, 0, water_tried=0, water_error="no counters2")], "locks": 0})
    now = PI.abs_tick(s)
    s["insane"]["list"][0]["water_tried"] = now - 100
    props, notes = run_rule(s)
    assert not [p for p in props if p.rule == "insane_water"], props
    assert "the last try failed (no counters2)" in notes[0], notes[0]
    s["insane"]["list"][0]["water_tried"] = now - 700
    props, _ = run_rule(s)
    assert [p for p in props if p.rule == "insane_water"], props


@test("brain: the bridge's water_more (past the listed rows) are watered too, each once")
def _():
    s = state({"list": [row(1, "raving", 41000, 0)], "locks": 0,
               "water_more": [{"id": 11, "name": "M", "kind": "raving", "thirst": 45000, "hunger": 0},
                              {"id": 1, "name": "dup", "kind": "raving", "thirst": 45000, "hunger": 0},
                              {"id": 12, "name": "B", "kind": "berserk", "thirst": 45000, "hunger": 0}]})
    props, _ = run_rule(s)
    assert [p.action["units"] for p in props if p.rule == "insane_water"] == [[1, 11]], props


@test("brain: insane_water False: nothing proposed, and the note says they will die of thirst unless turned on")
def _():
    s = state({"list": [row(1, "raving", 60000, 0)], "locks": 0})
    props, notes = run_rule(s, insane_water=False)
    assert not [p for p in props if p.rule == "insane_water"], props
    assert "the AI's water for them is off (insane_water)" in notes[0] and "(dehydrated)" in notes[0], notes[0]


@test("brain: an older bridge (no timers in the rows): the old words, nothing proposed")
def _():
    s = state({"list": [{"id": 1, "name": "A", "kind": "melancholy", "hazards": {}, "doors": 0, "locked": 0}],
               "locks": 0})
    props, notes = run_rule(s)
    assert props == [] and "nothing more can be done" in notes[0], (props, notes)


@test("brain: plan() sends insane_water through select()")
def _():
    s = state({"list": [row(7, "melancholy", 48000, 0)], "locks": 0})
    props, _notes = plan(s, Memory())
    from planner import select
    allowed, _ = select(props, s, Memory())
    acts = [p.action for p in allowed if p.rule == "insane_water"]
    assert acts == [{"type": "insane_water", "units": [7]}], [(p.rule, p.action) for p in allowed][:20]


@test("thirst rule: an insane melancholy / raving row is said to be watered by the insane rule; others as before")
def _():
    cfg = dict(PLANNER_CONFIG)
    ex = {"types": set(), "release_all": False, "release_ids": set(), "squad_attack": False}
    act, words = PT._remedy_old({"id": 1, "reason": "insane", "insane": "raving", "timer": 41000}, {}, cfg, ex)
    assert act is None and "sets their thirst back to 0 directly through DFHack from 40000" in words, words
    act, words = PT._remedy_old({"id": 1, "reason": "insane", "insane": "catatonic", "timer": 41000}, {}, cfg, ex)
    assert "nothing makes them drink" in words, words
    cfg["insane_water"] = False
    act, words = PT._remedy_old({"id": 1, "reason": "insane", "insane": "raving", "timer": 41000}, {}, cfg, ex)
    assert "nothing makes them drink" in words, words


@test("wiring: words, quiet camera, survival class, transient and critical for the refusal streak")
def _():
    import overseer_words as OW
    import hold_classes as HC
    import planner_refusal_streak as RS
    assert "insane_water" in OW.SHORT_WORDS and "insane_water" in OW.CAMERA_QUIET
    assert HC.rule_class("insane_water") == "survival"
    assert "insane_water" in RS.TRANSIENT_RULES and "insane_water" in RS.TRANSIENT_ACTIONS
    assert "insane_water" in RS.CRITICAL_RULES


finish()
