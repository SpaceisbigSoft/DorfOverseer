"""(0.105.35, group water) Nothing waits for the player: wells, the cistern,
the water works and the farms decide every case themselves. The cavern well
into an unfound cavern by the fort's state and sliders (the Rules switch off),
a rope's thread made by the AI, the cistern's well's workshop built, the
cistern retired after a second leak / a gap it can't close / a lever that
won't link (relinked first), a held water work retired, the pump labour given,
and the farms' notes. The bridge: cistern_step retire / relink, water_work
retire (not begun again for a while, never after twice); dry runs change nothing.

    python tests/test_r35_water.py
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
from harness import make_test, test as plain_test, finish  # noqa: E402
from planner import PLANNER_CONFIG, Memory, plan  # noqa: E402
import planner_wells  # noqa: E402
import planner_water  # noqa: E402
import overseer  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def you(notes: list) -> list:
    return [n for n in notes if n.startswith("[you]")]


def _const(path: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / path).read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


# ---- the brain ---------------------------------------------------------------------------

def thirsty(**kw) -> dict:
    s = {"settings": {"traits": dict(kw.pop("traits", {}))}, "dwarves": {"total": 40, "needs_medical_care": 0},
         "society": {"parched": 0}, "stocks": {"drink": 400}, "military": {"soldiers": 0}}
    for k, v in kw.items():
        s[k].update(v)
    return s


def army(n: int) -> dict:
    """(v35) n armed soldiers (ai_opens_cavern counts the armed only)."""
    return {"soldiers": n, "squads": [{"id": 1, "members": max(n, 1), "power": {"armed": n}}]}


@plain_test("cavern well into an unfound cavern: the AI decides by the fort's water and soldiers, and its sliders")
def _():
    ok, why = planner_wells.ai_opens_cavern(thirsty(), CFG)
    assert not ok and "isn't short of water" in why, why
    s = thirsty(dwarves={"needs_medical_care": 3}, military=army(2))
    ok, why = planner_wells.ai_opens_cavern(s, CFG)
    assert not ok and "only 2 armed soldier(s)" in why and "(3 wanted)" in why, why
    s["military"].update(army(3))
    assert planner_wells.ai_opens_cavern(s, CFG)[0]
    # Caution 50+: two more soldiers wanted; Militarism 50+: one fewer
    s["settings"]["traits"] = {"caution": 60}
    ok, why = planner_wells.ai_opens_cavern(s, CFG)
    assert not ok and "(5 wanted)" in why, why
    s["settings"]["traits"] = {"militarism": 60}
    s["military"].update(army(2))
    assert planner_wells.ai_opens_cavern(s, CFG)[0]
    # drink short: enough, but not at Caution +100 (only for the injured or parched)
    d = thirsty(stocks={"drink": 10}, military=army(4))
    assert planner_wells.ai_opens_cavern(d, CFG)[0]
    d["settings"]["traits"] = {"caution": 100}
    ok, why = planner_wells.ai_opens_cavern(d, CFG)
    assert not ok and "Caution" in why, why
    d["society"]["parched"] = 2
    d["military"].update(army(6))
    assert planner_wells.ai_opens_cavern(d, CFG)[0]


def unfound_fort() -> dict:
    s = fort()
    s["buildings"]["other"].pop("Well", None)
    s["projects"]["open"] = []
    s["dwarves"]["needs_medical_care"] = 4
    s["water"] = {"bodies": [{"kind": "cavern", "tiles": 12412, "stagnant_share": 0,
                              "nearest": {"x": 135, "y": 131, "z": 125, "d": 80}}]}
    for l in s["map"]["layers"]:
        if l["name"] == "Cavern1":
            l["discovered"] = False
    return s


@plain_test("cavern well: the switch off and no soldiers -> a plain note, never 'allow it on the Rules tab'")
def _():
    s = unfound_fort()
    s.setdefault("military", {}).update(army(0))
    m = Memory()
    m.well_failure = "no open drop from a free floor inside the fort to clean water (the water below is in a cavern)"
    props, notes = plan(copy.deepcopy(s), m)
    assert not [p for p in props if p.rule == "well" and p.action.get("cavern")]
    assert not any("allow it" in n or "Rules tab" in n for n in notes), notes
    assert not you(notes), you(notes)
    s["military"].update(army(4))
    props, notes = plan(copy.deepcopy(s), m)
    w = [p for p in props if p.rule == "well" and p.action.get("cavern")]
    assert w and w[0].action["open_caverns"] is True and "opens Cavern1 for the first time" in w[0].reason, \
        [(p.action, p.reason) for p in w]
    # the player's switch on: open_caverns as before, no "AI's call" words
    s["settings"]["open_caverns"] = True
    w = [p for p in plan(copy.deepcopy(s), m)[0] if p.rule == "well" and p.action.get("cavern")]
    assert w and w[0].action["open_caverns"] is True and "AI's call" not in w[0].reason


@plain_test("no well placed and the injured waiting: a plain note of what the AI does (no Needs you)")
def _():
    s = fort()
    s["buildings"]["other"].pop("Well", None)
    s["dwarves"]["needs_medical_care"] = 2
    m = Memory()
    m.well_failure = "no open drop from a free floor inside the fort to clean water"
    m.cavern_well_failure = "no floor inside the fort over cavern water with solid rock between"
    m.cavern_gallery_retried = True
    notes = plan(s, m)[1]
    assert not you(notes), you(notes)
    assert any("tries another spot" in n and "water source zone" in n for n in notes), notes


def well_waiting(**stocks) -> dict:
    s = fort()
    s["buildings"]["other"].pop("Well", None)
    s["projects"]["open"] = [{"id": 3, "kind": "well", "phase": "furnish",
                              "furnish": {"placed": 1, "done": 0, "waiting": {"Well": 1}, "days": 4}}]
    s["stocks"].update(mechanisms=1, chains=0, cloth=0, thread=0, **stocks)
    s.setdefault("supplies", {}).update(ropes=0, cloth_kinds={}, thread_kinds={}, buckets=1)
    s["military"].setdefault("gear", {})["forges"] = 0
    return s


@plain_test("a well's rope: thread from fibre plants, else wool sheared and spun; nothing to make it from: a note")
def _():
    s = well_waiting()
    s["supplies"]["thread_plants"] = 12
    s["buildings"]["workshops"]["Farmers"] = 1
    orders, shops, stuck = planner_wells.well_parts_plan(s)
    assert [o[0] for o in orders] == ["process_plants"] and not stuck, (orders, stuck)
    s["supplies"]["thread_plants"] = 0
    s["supplies"]["shearable"] = 3
    orders, shops, stuck = planner_wells.well_parts_plan(s)
    assert [o[0] for o in orders] == ["shear_creature", "spin_thread"] and not stuck, (orders, stuck)
    # no farmer's workshop: it is built (not asked of the player)
    s["buildings"]["workshops"].pop("Farmers")
    s["supplies"]["thread_plants"] = 5
    orders, shops, stuck = planner_wells.well_parts_plan(s)
    assert shops == ["Farmers"] and not orders, (orders, shops)
    s["supplies"]["thread_plants"] = 0
    s["supplies"]["shearable"] = 0
    orders, shops, stuck = planner_wells.well_parts_plan(s)
    assert stuck and "caravan" in stuck[0], stuck
    notes = plan(s, Memory())[1]
    assert not [n for n in you(notes) if "well" in n], you(notes)


@plain_test("the cistern's well: a missing workshop is dug and built by the AI; what it can't make is a note")
def _():
    s = well_waiting()
    s["projects"]["open"] = []
    s["buildings"]["workshops"].pop("Mechanics", None)
    s["stocks"]["mechanisms"] = 0
    props, notes = [], []
    planner_wells._cistern_parts(s, {"stage": "well"}, props, notes)
    ws = [p for p in props if p.action.get("type") == "start_project"]
    assert ws and "Mechanics" in ws[0].action["shops"] and ws[0].action["urgent"], [p.action for p in props]
    assert not you(notes), notes


def cistern(**st) -> dict:
    s = fort()
    s["water"] = dict(s.get("water") or {}, cistern_status=dict({"v": 2, "stage": "filling", "gate": "shut",
                                                                 "depth": 2}, **st))
    return s


@plain_test("cistern: one leak waits (the bridge tries once more), a second retires it; never a Needs you")
def _():
    props, notes = plan(cistern(leak="x5 y6 elevation 41", leaks=1), Memory())
    # (v35) the plain step: the bridge clears the leak in it once dry and closed all round
    c = [p for p in props if p.rule == "cistern"]
    assert [p.action.get("retire") for p in c] == [None] and not you(notes), (c, notes)
    props, notes = plan(cistern(leak="x5 y6 elevation 41", leaks=2), Memory())
    c = [p for p in props if p.rule == "cistern"]
    assert len(c) == 1 and c[0].action["type"] == "cistern_step" and c[0].action["retire"] is True, \
        [p.action for p in c]
    assert not you(notes), notes
    assert overseer.short(c[0].action) == "retire the cistern (its floodgate shut)"
    assert overseer.short({"type": "cistern_step", "relink": True}).startswith("the cistern: ask for its lever link")


@plain_test("a held water work is retired by the AI (its floodgate shut); a stalled pump gets the pump labour")
def _():
    s = fort()
    s["waterworks"] = {"works": {"irrigation": {"kind": "irrigation", "stage": "held",
                                                "why": "the floor dried without mud"}}, "refused": {}}
    props, notes = [], []
    planner_water._waterworks_rule(s, Memory(), CFG, props, notes)
    assert [p.action for p in props] == [{"type": "water_work", "kind": "irrigation", "retire": True,
                                          "why": "the floor dried without mud"}], [p.action for p in props]
    assert not you(notes), notes
    assert overseer.short(props[0].action) == "retire the muddied farm level (its floodgate shut)"
    s["waterworks"] = {"works": {"pump": {"kind": "pump", "stage": "filling", "stalled": True, "lift": 3}},
                       "refused": {}}
    props, notes = [], []
    planner_water._waterworks_rule(s, Memory(), CFG, props, notes)
    lab = [p for p in props if p.action["type"] == "assign_labor"]
    assert lab and lab[0].action == {"type": "assign_labor", "job": "OPERATE_PUMP", "count": 3}, [p.action for p in props]
    assert CFG["waterworks_pump_labor_cooldown_ticks"] == 14 * 1200
    assert not you(notes), notes


@plain_test("farms: no brewable seeds, or no soil while hungry: notes of what the AI does, no Needs you")
def _():
    src = (ROOT / "brain" / "planner_farms.py").read_text(encoding="utf-8")
    assert "ask_player" not in src
    src_w = (ROOT / "brain" / "planner_wells.py").read_text(encoding="utf-8")
    src_ww = (ROOT / "brain" / "planner_water.py").read_text(encoding="utf-8")
    assert "ask_player" not in src_w and "ask_player" not in src_ww
    assert "yourself" not in src_w and "allow it on the Rules tab" not in src_w


# ---- the bridge --------------------------------------------------------------------------

if LuaRuntime is not None:
    def boot():
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().LUA_DIR = str(ROOT / "lua")
        layouts = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
        builder = (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8")
        B, W = lua.execute(_const("test_builder.py", "HARNESS"), layouts, builder)
        lua.execute("df = {global = {cur_year = 148, cur_year_tick = 100}}")
        return lua, B, W

    LUA, B, W = boot()
    GAME_FAKE = _const("test_builder.py", "GAME_FAKE")
    GAME_CLEAN = _const("test_builder.py", "GAME_CLEAN")
    STORE = LUA.execute("""
        local B = ...
        local S = {}
        B.site_get = function(k, d) return S[k] or d or {} end
        B.site_put = function(k, v) S[k] = v end
        B.cistern_data = function() local d = S['ai-overseer/cistern']; return d and d.stage and d or nil end
        return S
    """, B)

    def put_cistern(**d):
        base = {"stage": "linking", "relinks": 3,
                "plan": LUA.table_from({"floodgate": LUA.table_from({"x": 80, "y": 50}), "intake_z": 60,
                                        "cistern": LUA.table_from({"z": 60, "x1": 1, "y1": 1, "x2": 5, "y2": 5}),
                                        "source": "pool"})}
        base.update(d)
        STORE["ai-overseer/cistern"] = LUA.table_from(base)
        STORE["ai-overseer/cistern/retired"] = None

    def _reset():
        W.reset()

    test = make_test(before=_reset)

    @test("bridge: cistern_relink resets the link count (2 rounds at most); a dry run changes nothing")
    def _():
        put_cistern()
        r = B.cistern_relink(True)
        assert r.ok and r.dry_run and STORE["ai-overseer/cistern"].relinks == 3
        r = B.cistern_relink(False)
        d = STORE["ai-overseer/cistern"]
        assert r.ok and d.relinks == 0 and d.relink_rounds == 1, dict(r)
        d.relink_rounds = 2
        r = B.cistern_relink(False)
        assert not r.ok and r.rejected and "afresh 2 times" in r.error, r.error
        put_cistern(stage="filling")
        assert not B.cistern_relink(False).ok

    @test("bridge: cistern_retire shuts an open floodgate, puts it with the retired, at most 3; dry run changes nothing")
    def _():
        LUA.execute(GAME_FAKE)
        try:
            LUA.execute("""
              df.building_type[9] = 'Floodgate'; df.building_type.Floodgate = 9
              function MKGATE(x, y, z, closed)
                local b = MKS(x, y, z, 9, true)
                b.gate_flags = {closed = closed}
                return b
              end
            """)
            gate = LUA.eval("MKGATE")(80, 50, 60, False)
            lever = LUA.eval("MKS")(82, 50, 70, 8, True, 3)
            put_cistern(stage="done", lever_id=lever.id)
            r = B.cistern_retire(True, "leaked twice")
            assert r.ok and r.dry_run and STORE["ai-overseer/cistern"].stage == "done" \
                and STORE["ai-overseer/cistern/retired"] is None
            assert gate.gate_flags.closed is False
            pulls = LUA.execute("local B = ...; local P = {}; local real = B.pull; "
                                "B.pull = function(id, instant) P[#P + 1] = {id = id, instant = instant} return true end; "
                                "return P", B)
            r = B.cistern_retire(False, "leaked twice")
            assert r.ok and r.retired, dict(r)
            assert len(pulls) == 1 and pulls[1].id == lever.id and pulls[1].instant is True, "the floodgate shut at once"
            old = STORE["ai-overseer/cistern/retired"]
            assert len(old) == 1 and old[1].by_ai and old[1].why == "leaked twice"
            assert B.cistern_data() is None
            assert not B.cistern_retire(False, "x").ok              # nothing left to retire
            # at most CISTERN_RETIRE_MAX by the AI
            for _ in range(2):
                STORE["ai-overseer/cistern"] = LUA.table_from({"stage": "linking", "plan": LUA.table_from({
                    "floodgate": LUA.table_from({"x": 1, "y": 1}), "cistern": LUA.table_from({"z": 60})})})
                assert B.cistern_retire(False, "again").ok
            STORE["ai-overseer/cistern"] = LUA.table_from({"stage": "linking", "plan": LUA.table_from({
                "floodgate": LUA.table_from({"x": 1, "y": 1}), "cistern": LUA.table_from({"z": 60})})})
            r = B.cistern_retire(False, "fourth")
            assert not r.ok and r.rejected and "retired 3 cisterns" in r.error, dict(r)
        finally:
            LUA.execute(GAME_CLEAN)

    WW_SRC = (ROOT / "lua" / "ai-waterworks.lua").read_text(encoding="utf-8")
    WW_FAKE = _const("test_waterworks.py", "FAKE")

    @test("bridge: water_work retire: not begun again for a while (refused), never after twice; dry run changes nothing")
    def _():
        env = LUA.execute(WW_FAKE, WW_SRC)
        Wd = env.W
        st = env.load_state()
        st.works["irrigation"] = LUA.table_from({"kind": "irrigation", "stage": "held", "why": "dried without mud",
                                                 "plan": LUA.table_from({"gate": LUA.table_from({"x": 1, "y": 1, "z": 90})})})
        env.save_state(st)
        r = env.step("irrigation", LUA.table_from({"retire": True, "why": "dried without mud", "dry_run": True}))
        assert r.ok and r.dry_run and env.load_state().works["irrigation"].stage == "held"
        r = env.step("irrigation", LUA.table_from({"retire": True, "why": "dried without mud"}))
        st = env.load_state()
        assert r.ok and st.works["irrigation"].stage == "retired", dict(r)
        assert st.refused["irrigation"].why == "retired: dried without mud" and st.refused["irrigation"].retired == 1
        st.retired_n["irrigation"] = 2
        env.save_state(st)
        r = env.step("irrigation", LUA.table_from({}))
        assert not r.ok and r.rejected and "retired 2 times" in r.error, dict(r)
        assert Wd is not None

    @plain_test("bridge: cistern_step passes retire (with why) and relink to the builder")
    def _():
        src = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")
        assert "cistern_retire(a.dry_run == true" in src and "cistern_relink(a.dry_run == true)" in src
        for f in ("ai-builder-cistern.lua", "ai-bridge-actions.lua", "ai-waterworks.lua", "ai-bridge.lua"):
            text = (ROOT / "lua" / f).read_text(encoding="utf-8")
            assert LUA.eval("function(s, n) local f, e = load(s, n, 't', {}); return e end")(text, f) is None, f

finish(None if LuaRuntime is not None else "these tests need the lupa package (pip install lupa)")
