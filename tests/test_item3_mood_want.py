"""(0.105.112 item3) One reading of a mood request's want; the part-used cloth
by DF's min_dimension; the smelter's fuel made for a bar mood.

B, 24 Nov 22:28-22:40: Sigun's secretive mood wanted yarn cloth first and
plant cloth fourth; `mood` and `mood_hospital` each read the fibre their own
way, and hospital_release was asked four times for the hospital's yarn
thread (all part-used: "nothing of that kind"). D, 22-24 Nov: three moods
read "1 cloth (yarn) on hand" from one 80% llama wool cloth for 40 days (DF
asks a cloth as 1 item with min_dimension 10000, so the bridge's partial test
never held); eight bar moods got "no fuel for the smelter" and nothing done.

    python tests/test_item3_mood_want.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

import planner_moods  # noqa: E402
import planner_mood_help as MH  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG, abs_tick, TICKS_PER_DAY  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"


def av(**kw):
    a = {"free": 0, "reach": 0, "forbidden": 0, "forbidden_reach": 0, "dump": 0, "job": 0, "other": 0,
         "held": 0, "trader": 0, "hospital": 0}
    a.update(kw)
    return a


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["orders"] = []
    s["buildings"]["workshops"]["Loom"] = 1
    s.setdefault("supplies", {})
    s["supplies"].update({"thread_kinds": {"plant": 0, "silk": 0, "yarn": 0},
                          "hospital": {"thread": 5, "cloth": 0,
                                       "thread_kinds": {"plant": 0, "silk": 0, "yarn": 5},
                                       "cloth_kinds": {"plant": 0, "silk": 0, "yarn": 0}}})
    s["health"] = {"patients": [], "waiting": 0, "stitch_wait": 0}
    s["mood_help"] = {"cancels": []}
    return s


def mood(missing):
    return {"unit_id": 5, "name": "Sigun", "mood": "Secretive", "craft": True, "skill": "CUTGEM",
            "workshop": "Jewelers", "items_have": 0, "items_needed": len(missing), "missing": missing,
            "thirst": 100}


def memory(s) -> Memory:
    m = Memory()
    m.moods_seen = {"5": abs_tick(s) - 2 * TICKS_PER_DAY}
    return m


@test("mood_want: the fibre from DF's flags, else the material; 'any' when none; part_ok by min_dimension")
def _():
    w = MH.mood_want({"item": "CLOTH", "flags": ["yarn"]})
    assert w["what"] == "cloth" and w["fibres"] == ("yarn",) and w["fibre"] == "yarn" and not w["part_ok"], w
    w = MH.mood_want({"item": "CLOTH", "flags": [], "material": "cave spider silk"})
    assert w["fibre"] == "silk", w
    w = MH.mood_want({"item": "CLOTH", "flags": []})
    assert w["fibres"] == () and w["fibre"] == "any", w
    w = MH.mood_want({"item": "THREAD", "flags": ["plant"]})
    assert w["what"] == "thread" and w["fibre"] == "plant" and w["part_ok"], w
    assert MH.mood_want({"item": "THREAD", "flags": [], "min_dim": 15000})["part_ok"] is False
    assert MH.mood_want({"item": "BAR", "flags": ["metal"]})["what"] == "bar"


@test("mood and mood_hospital read a request the same: _fibre_of, _cloth_or_thread, the trade key")
def _():
    for x in ({"item": "CLOTH", "flags": ["yarn"]}, {"item": "CLOTH", "flags": ["plant"]},
              {"item": "THREAD", "flags": ["silk"]}, {"item": "CLOTH", "flags": []}):
        w = MH.mood_want(x)
        assert planner_moods._fibre_of(x) == w["fibre"], x
        assert planner_moods._cloth_or_thread(x) == w["what"], x
    s = fort()
    s["moods"] = {"list": [mood([{"index": 0, "item": "CLOTH", "quantity": 1, "flags": ["yarn"],
                                  "avail": av(trader=33)}])]}
    assert [w["key"] for w in planner_moods.mood_trade_wants(s)] == ["CLOTH:YARN"]


@test("Sigun: the yarn cloth's mood_hospital release is yarn; once 'nothing of that kind', not asked again "
      "while the hospital's counts stay")
def _():
    s = fort()
    x = {"index": 0, "item": "CLOTH", "quantity": 1, "flags": ["yarn"], "avail": av(trader=33)}
    s["moods"] = {"list": [mood([x])]}
    mem = memory(s)
    props, notes = [], []
    planner_moods.mood_hospital_rule(s, mem, CFG, props, notes)
    assert [p.action for p in props] == [{"type": "hospital_release", "thread": 1, "kind": "yarn"}], \
        [p.action for p in props]
    r = {"ok": False, "rejected": True, "error": "nothing of that kind in the hospital that can be taken "
                                                 "(whole, in no job, owned by nobody), and its quotas are 0 already"}
    MH.note_mood_help(props[0], r, s, mem, abs_tick(s))
    props = []
    planner_moods.mood_hospital_rule(s, mem, CFG, props, [])
    assert not props, [p.action for p in props]
    # the hospital's counts change: asked again
    s["supplies"]["hospital"]["thread_kinds"]["yarn"] = 6
    planner_moods.mood_hospital_rule(s, mem, CFG, props, [])
    assert [p.action.get("kind") for p in props] == ["yarn"], [p.action for p in props]


@test("a bar mood with no fuel: charcoal from wood (never coke: it burns a fuel), else an inside tree felled")
def _():
    s = fort()
    s["buildings"]["furnaces"] = {"Smelter": 1, "WoodFurnace": 1}
    s["supplies"]["fuel"] = 0
    s["industry"] = {"ore_stock_by": {"LIMONITE": {"n": 5, "metals": ["IRON"]}}}
    s["stocks"]["wood"] = 19
    s["stone_use"] = {"economic": {}}
    x = {"index": 0, "item": "BAR", "quantity": 1, "flags": ["metal"], "avail": av()}
    acts, why = planner_moods._mood_make(s, x, "bar", memory(s), CFG, mood={"name": "Nil", "unit_id": 5})
    assert why is None and [a.get("recipe") for a, _ in acts] == ["make_charcoal"], (acts, why)
    s["stone_use"] = {"economic": {"LIGNITE": {"n": 4}}}
    acts, why = planner_moods._mood_make(s, x, "bar", memory(s), CFG, mood={"name": "Nil", "unit_id": 5})
    # (0.105.119 item41) coal at fuel 0 is no help: the coke reaction itself burns one fuel
    # (D, 25 Nov: "Needs refined coal", twice): charcoal still
    assert [a.get("recipe") for a, _ in acts] == ["make_charcoal"], acts
    # no coal, no wood: one of the fort's own trees within reach felled
    s["stone_use"] = {"economic": {}}
    s["stocks"]["wood"] = 0
    s["forestry"] = {"inside": {"reachable": 3, "reach_marked": 0}}
    acts, why = planner_moods._mood_make(s, x, "bar", memory(s), CFG, mood={"name": "Nil", "unit_id": 5})
    assert [a.get("type") for a, _ in acts] == ["cavern_logging"], (acts, why)
    # nothing at all: said, with why
    s["forestry"] = {"inside": {"reachable": 0}}
    acts, why = planner_moods._mood_make(s, x, "bar", memory(s), CFG, mood={"name": "Nil", "unit_id": 5})
    assert not acts and "no fuel" in why and "wood" in why, (acts, why)


@test("Lua: a part-used piece is judged by DF's min_dimension (cloth 10000 as 1 item), min_dim reported")
def _():
    src = (LUA / "ai-moods.lua").read_text(encoding="utf-8")
    i = src.index("local function partial_cloth")
    body = src[i:src.index("\nend", i)]
    assert "min_dimension" in body and "ji.quantity >= 1000" not in body, body
    assert "min_dim = " in src
    mh = (LUA / "ai-mood-help.lua").read_text(encoding="utf-8")
    assert "a.part_ok == true and 13500 or THREAD_WHOLE" in mh


finish()
