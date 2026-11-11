"""(0.105.31) Mood reserves. F (the Garden fort), 8 Nov: two dwarves died
after failed strange moods, the latest a weaver wanting 3 plant cloth while
the supplies counted 2 (the mood's own count: 0), no plant thread and no
fibre crop. A mood lasts about 40 days, too short to grow fibre, so the fort
keeps a few of each common mood material on hand (brain/planner_moods.py
_mood_reserve_rule, by the existing recipes; reserve_room holds the AI's
other orders that would use one up), the farms put a fibre crop on one plot
(lua set_farm_crops, params.thread), the mood's count is taken again when a
new item of its kind is made (lua/ai-moods.lua cached_avail), and the Needs
you names the reserve gap and what is being done.

    python tests/test_fix31_reserves.py
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
from planner import PLANNER_CONFIG, Memory, plan, select  # noqa: E402
from planner_core import NEEDS_YOU, Proposal  # noqa: E402
from planner_moods import (_mood_materials, _mood_reserve_rule, reserve_room,  # noqa: E402
                           reserve_trade_wants, mood_reserve_counts)
from planner_trade import trade_wants  # noqa: E402

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


def garden(**sup) -> dict:
    """F at 252 winter: plant cloth 2, no plant thread or fibre plants, no fibre crop."""
    s = copy.deepcopy(BASE)
    su = s.setdefault("supplies", {})
    su.update({"cloth_kinds": {"plant": 2, "silk": 0, "yarn": 6}, "thread_kinds": {"plant": 0, "silk": 0, "yarn": 0},
               "thread_plants": 0, "hides": 0})
    su.update(sup)
    s["farms"] = {"crops": {k: {"name": k.lower(), "seeds": 10, "planted": 1} for k in
                            ("BERRIES_STRAW", "GRASS_WHEAT_CAVE", "MUSHROOM_HELMET_PLUMP", "PEAR", "POD_SWEET",
                             "POTATO", "WHITE_MILLET")},
                  "plot_list": [{"id": 1, "ok_now": True, "options": 3}]}
    return s


def reserve_props(s, memory=None):
    props, notes = [], []
    _mood_reserve_rule(s, memory if memory is not None else Memory(), CFG, props, notes)
    return props, notes


# ---- (b) the reserve rule ----------------------------------------------------------------

@test("reserves 1: F's supplies: no plant thread, plants or fibre seed -> said once, plant cloth and seeds asked of caravans")
def _():
    s = garden()
    m = Memory()
    props, notes = reserve_props(s, m)
    assert not [p for p in props if p.rule == "mood_reserve" and "cloth" in str(p.action)], props
    assert any("2 plant cloth, a reserve of 3 kept for strange moods" in n for n in notes), notes
    assert not reserve_props(s, m)[1] or not any("plant cloth" in n for n in reserve_props(s, m)[1])
    keys = {w["key"]: w["count"] for w in reserve_trade_wants(s, CFG)}
    assert keys == {"CLOTH": 1, "SEEDS": 5}, keys
    assert any(w["key"] == "SEEDS" for w in trade_wants(s, CFG, 30))
    # never a slaughter for a reserve (the Beast-friends ban untouched)
    assert not [p for p in props if p.action.get("type") == "slaughter_one"]


@test("reserves 2: plant thread at hand -> woven; fibre plants -> processed before the still; fibre seeds -> a fibre plot")
def _():
    props, _ = reserve_props(garden(thread_kinds={"plant": 5}))
    # (reserve fixes) up to a batch over the line: 3 + 2 - 2
    assert props[0].action == {"type": "work_order", "recipe": "weave_plant_cloth", "amount": 3}, props
    assert "kept for strange moods" in props[0].reason
    props, _ = reserve_props(garden(thread_plants=4))
    assert props[0].action == {"type": "work_order", "recipe": "process_plants", "amount": 3}, props
    assert "before the still" in props[0].reason
    s = garden()
    s["farms"]["crops"]["GRASS_TAIL_PIG"] = {"name": "pig tail", "seeds": 6, "planted": 0, "thread": True}
    props, _ = reserve_props(s)
    assert props[0].action == {"type": "set_farm_crops", "thread": True, "drink": False}, props
    assert "pig tail" in props[0].reason
    s["farms"]["crops"]["GRASS_TAIL_PIG"]["planted"] = 1          # grows already: nothing to set
    assert not [p for p in reserve_props(s)[0] if p.action.get("type") == "set_farm_crops"]
    assert reserve_trade_wants(s, CFG) == []                      # it can be made here


@test("reserves 3: at the reserve nothing is ordered with nothing to make it of; leather tanned, a gem cut over the rough reserve, blocks made")
def _():
    s = garden(cloth_kinds={"plant": 3, "silk": 2, "yarn": 0})
    assert not reserve_props(s)[0]
    s["stocks"]["leather"] = 0
    s["supplies"]["hides"] = 4
    assert reserve_props(s)[0][0].action == {"type": "work_order", "recipe": "tan_hide", "amount": 4}
    s["stocks"]["leather"] = 5
    s["stocks"]["cut_gems"], s["stocks"]["rough_gems"] = 0, 3
    s["trade"] = dict(s.get("trade") or {}, rough_gem={"n": 3, "token": "INORGANIC:AGATE"})
    a = reserve_props(s)[0][0].action
    assert a == {"type": "work_order", "recipe": "cut_gems", "amount": 1, "material": "INORGANIC:AGATE"}, a   # rough 3 - 2 kept
    s["stocks"]["rough_gems"] = 2                                 # only its own reserve: not cut
    assert not reserve_props(s)[0]
    s["stocks"]["blocks"] = 1
    assert reserve_props(s)[0][0].action == {"type": "work_order", "recipe": "stone_blocks", "amount": 6}
    cfg = dict(CFG, reserve_blocks=0)                             # 0 turns a reserve off
    props = []
    _mood_reserve_rule(s, Memory(), cfg, props, [])
    assert not props


def _held(s):
    """(0.105.33) the orders select() holds for a reserve: no room over its line"""
    return {r: w for r, (room, w) in reserve_room(s, CFG).items() if room <= 0}


@test("reserves 4: the AI's orders that would use a reserve up wait at or under it (bags, bone crafts, gem cutting)")
def _():
    s = garden(cloth_kinds={"plant": 3, "silk": 0, "yarn": 9})
    s["needs"] = dict(s.get("needs") or {}, bones=5)
    held = _held(s)
    assert "cloth_bag" in held and "bone_crafts" in held and "yarn_bag" not in held, held
    s["needs"]["bones"] = 6
    s["supplies"]["cloth_kinds"]["plant"] = 4
    held = _held(s)
    assert "cloth_bag" not in held and "bone_crafts" not in held, held
    s["supplies"]["cloth_kinds"]["plant"] = 1
    p_bag = Proposal("bags", {"type": "work_order", "recipe": "cloth_bag", "amount": 5}, "bags", 5, True)
    p_res = Proposal("mood_reserve", {"type": "work_order", "recipe": "cloth_bag", "amount": 1}, "x", 5, True)
    allowed, why = select([p_bag], s, Memory())
    assert not allowed and any("kept for strange moods" in w for w in why), why
    allowed, _ = select([p_res], s, Memory())
    assert allowed
    # unknown counts (an older bridge) hold nothing
    assert _held(copy.deepcopy(BASE)) == {}


@test("reserves 5: default plan() unchanged where no reserve applies (the big fort: counts unknown or plenty)")
def _():
    s = copy.deepcopy(BASE)
    a = plan(copy.deepcopy(s), Memory())
    assert not [p for p in a[0] if p.rule == "mood_reserve"]
    assert not [n for n in a[1] if "kept for strange moods" in n]
    assert mood_reserve_counts(s)["plant_cloth"] is None


# ---- (c) the Needs you ----------------------------------------------------------------

WEAVER = [{"item": "CLOTH", "flags": ["plant"], "quantity": 3,
           "avail": {"free": 0, "reach": 0, "forbidden": 0, "dump": 0, "job": 0, "other": 0}},
          {"item": "WOOD", "quantity": 1, "avail": {"free": 8, "reach": 1, "other": 3, "enough": True}}]


@test("reserves 6: F's weaver: the Needs you names the reserve gap, the count mismatch and what is done")
def _():
    s = garden()
    props, notes = [], []
    _mood_materials(s, "Logem", "Fey", copy.deepcopy(WEAVER), 5, props, notes, CFG, memory=Memory(), unit_id=7)
    asks = [n for n in notes if n.startswith(NEEDS_YOU)]
    assert asks, notes
    a = asks[0]
    assert "no plant thread to weave" in a and "reserve of plant cloth for moods is 2 of 3" in a, a
    assert "the 2 counted may be newer than the mood's count" in a, a
    assert "asked of the caravans" in a, a
    # with fibre seeds: the crop is named as being set
    s["farms"]["crops"]["GRASS_TAIL_PIG"] = {"name": "pig tail", "seeds": 6, "planted": 0, "thread": True}
    props, notes = [], []
    _mood_materials(s, "Logem", "Fey", copy.deepcopy(WEAVER), 5, props, notes, CFG, memory=Memory(), unit_id=7)
    a = [n for n in notes if n.startswith(NEEDS_YOU)][0]
    assert "fibre crop (pig tail) is set on the farms" in a, a


# ---- (a) the mood's count and the farms (lua) ---------------------------------------------

if LuaRuntime is not None:
    @test("reserves 7: the mood's count is taken again at once when a cloth is woven (a list grew); kept otherwise")
    def _():
        lua = LuaRuntime(unpack_returned_tuples=True)
        W = lua.execute(_const("test_moods.py", "FAKE"), module_src("ai-moods.lua"))
        M = W.env
        reqs = lua.table_from([lua.table_from({"t": 1, "kind": "plant", "q": 30000,
                                               "flags": lua.table_from(["plant"])})])
        j = W.job(reqs, lua.table())
        u = W.unit(3, j)
        W.item(1, "plant", 150, lua.table_from({"forbid": True, "trader": True}))   # a trader's, out of walk
        assert M.mood_report(j, u)[1].avail.free == 0
        W.item(1, "plant", 1)                                     # woven: the CLOTH list grew
        a = M.mood_report(j, u)[1].avail
        assert a.free == 1 and a.reach == 1, dict(a)
        for _ in range(2):
            W.item(1, "plant", 1)
        a = M.mood_report(j, u)[1].avail
        assert a.reach == 3 and a.enough
        W.item(1, "plant", 1)                                     # enough already: kept
        assert M.mood_report(j, u)[1].avail.reach == 3

    @test("reserves 8: set_farm_crops with thread swaps one AI-set plot to a fibre crop where none grows")
    def _():
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().LUA_DIR = str(ROOT / "lua")
        B, W = lua.execute(_const("test_builder.py", "HARNESS"),
                           (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8"),
                           (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8"))
        FF = lua.execute(_const("test_builder.py", "FARM_FAKE"), B)
        seeds = lua.table_from([lua.table_from(x) for x in ([1, 60], [2, 30])])
        plots = FF.setup(seeds, lua.table_from([lua.table_from(x) for x in ([31, True, 0], [32, True, 10])]))
        assert B.set_farm_crops(lua.table_from({}), False).ok
        season = B.current_season()

        def fibre():
            return [b.id for b in plots.values() if b.plant_id[season] == 4]
        assert not fibre()
        lua.execute("table.insert(df.global.world.items.other.SEEDS, {flags = {}, "
                    "getMaterialIndex = function() return 4 end, getStackSize = function() return 8 end})")
        r = B.set_farm_crops(lua.table_from({}), False)           # no thread asked: the AI's crops kept
        assert not fibre(), dict(r)
        r = B.set_farm_crops(lua.table_from({"thread": True}), False)
        assert r.ok and len(fibre()) == 1, (dict(r), fibre())
        r = B.set_farm_crops(lua.table_from({"thread": True}), False)   # one grows: no second
        assert len(fibre()) == 1 and r.changed == 0, dict(r)


if __name__ == "__main__":
    sys.exit(finish())
