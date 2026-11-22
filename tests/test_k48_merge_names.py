"""(0.105.48, K7a) Merge leftovers and wrong names (audits A1, A7, A9, A12):

  * needs.stressed: one row a dwarf (a merge left a second insert), the row
    carrying fight_need and child together;
  * plan()'s Stockpile buffer set once (the old factor line was left after it);
  * DF / DFHack names: ZONE_POND (not ZONE_PIT_POND), no dfhack.burrows.listUnits,
    no buildings.other.SIEGEENGINE;
  * homes: roomless households that can't walk to the free bedrooms get
    bedrooms dug (not only a note), the cut-off rooms' levels named;
  * drunkenness (inebriation) is no deadly syndrome, and one syndrome note, not two;
  * deep_descent (Verticality's cavern crossing) off by default, no preset turns it on.

    python tests/test_k48_merge_names.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import module_src, split_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import PLANNER_CONFIG  # noqa: E402
from planner_core import player_rules  # noqa: E402
import planner_homes as PH  # noqa: E402
import planner_society as PSo  # noqa: E402
import planner_descent as PD  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"


def lua_text(name: str) -> str:
    return split_src(name)   # (r8) a hub and its parts (ai-threats): their texts together


def code_lines(text: str) -> str:
    """The Lua without its comments (line comments only: enough here)."""
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


# --- 1. needs.stressed: one row a dwarf ---------------------------------------------------

@test("needs.stressed: one row a miserable soldier, with fight_need and child together (A1)")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    hyg = (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8")
    harness = re.search(r'HARNESS = r"""(.*?)"""', hyg, re.S).group(1)
    L = LuaRuntime(unpack_returned_tuples=True)
    H = L.execute(harness, lua_text("ai-bridge.lua"), str(LUA_DIR))
    H.scripts = L.table()
    M = H.module()
    H.df.need_type = L.eval("{[1] = 'MartialTraining', [2] = 'Socialize'}")
    # a child soldier (the stub's isAdult says no) whose training need is met (focus 0)
    unit = L.eval("""{id = 4, status = {current_soul = {personality = {needs = {
                          {id = 1, focus_level = 0, deity_id = -1}, {id = 2, focus_level = -20000, deity_id = -1}}}}},
                      military = {squad_id = 3, squad_position = 2}, owned_buildings = {}}""")
    H.dfhack.units.getCitizens = L.eval("function(u) return function() return {u} end end")(unit)
    H.dfhack.units.getStressCategory = L.eval("function() return 0 end")
    H.dfhack.units.isAdult = L.eval("function() return false end")
    H.dfhack.units.getReadableName = L.eval("function() return 'Urist' end")
    H.dfhack.df2utf = L.eval("function(x) return x end")
    n = M.get_needs()
    rows = [n.stressed[k] for k in n.stressed]
    assert len(rows) == 1, len(rows)
    r = rows[0]
    assert r.fight_need is True and r.child is True and r.squad is True, (r.fight_need, r.child, r.squad)


# --- 2. the Stockpile buffer ----------------------------------------------------------

@test("plan(): the Stockpile buffer is set once, by stock_factor (A9, A12)")
def _():
    tree = ast.parse((ROOT / "brain" / "planner.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "plan")
    sets = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "buffer" for t in n.targets)]
    assert len(sets) == 1, [ast.unparse(n) for n in sets]
    assert "stock_factor" in ast.unparse(sets[0].value), ast.unparse(sets[0])


# --- 3. DF and DFHack names -----------------------------------------------------------

@test("names: the pit zones read from ZONE_POND (DF 53.17), ZONE_PIT_POND only as a fallback (A12)")
def _():
    for name in ("ai-captives.lua", "ai-threats.lua"):
        code = code_lines(lua_text(name))
        assert "other.ZONE_POND" in code, name
        for line in code.splitlines():
            if "ZONE_PIT_POND" in line:
                assert "if not ok or not v then" in line, (name, line)
    # df-structures 53.17-r1 df.building.xml: buildings_other_id has ZONE_POND; no SIEGEENGINE vector
    names = set()
    for p in LUA_DIR.glob("*.lua"):
        code = code_lines(p.read_text(encoding="utf-8"))
        if "burrows.listUnits" in code:
            names.add((p.name, "dfhack.burrows.listUnits"))
        if "other.SIEGEENGINE" in code:
            names.add((p.name, "buildings.other.SIEGEENGINE"))
    assert not names, sorted(names)


SIEGE_STUB = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local B = {}
local strict = function(t) return setmetatable(t, {__index = function(_, k) error('no field ' .. k) end}) end
env.df = {global = {world = {buildings = {all = B, other = strict({})}}},
          building_type = {SiegeEngine = 'SiegeEngine', Door = 'Door'},
          siegeengine_type = {[0] = 'Catapult', [1] = 'Ballista'},
          building_siegeenginest = {}}
env.dfhack = {persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end}}
env.reqscript = function(n) return setmetatable({}, {__index = function() return function() end end}) end
env.require = function(n) return {} end
local ok, err = pcall(function() assert(load(src, 'ai-siege', 't', env))() end)
table.insert(B, {id = 5, centerx = 1, centery = 2, z = 3, type = 1, getType = function() return 'SiegeEngine' end,
                 getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end})
table.insert(B, {id = 6, getType = function() return 'Door' end})
return env, ok, err
"""


@test("siege: engines() walks the building list (no SIEGEENGINE vector) and finds the ballista")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    L = LuaRuntime(unpack_returned_tuples=True)
    env, ok, err = L.execute(SIEGE_STUB, module_src("ai-siege.lua"))
    assert ok, err
    out = env.engines()
    rows = [out[k] for k in out]
    assert len(rows) == 1 and rows[0].id == 5 and rows[0].kind == "ballista", [(r.id, r.kind) for r in rows]


# --- 4. homes: cut-off free rooms ------------------------------------------------------

def homes_state(**h):
    base = {"free_bedrooms": 12, "rooms_wanted": 7, "rooms_reachable": 0}
    base.update(h)
    return {"homes": base, "projects": {"open": []}, "settings": {}}


@test("homes: 7 roomless can walk to none of 12 free bedrooms: bedrooms dug for them, the cut-off levels named (A7)")
def _():
    props, notes = [], []
    PH._homes_rules(homes_state(free_cut_z=[88, 91]), PLANNER_CONFIG, {}, props, notes)
    dig = [p for p in props if p.rule == "homes_dig"]
    assert dig and dig[0].action["kind"] == "bedrooms", [(p.rule, p.action) for p in props]
    assert dig[0].action["rooms"] == 7 + PLANNER_CONFIG["min_spare_beds"], dig[0].action
    assert "12 of them out of their reach" in dig[0].reason, dig[0].reason
    note = [n for n in notes if "can't walk to any" in n]
    assert note and "z 88, 91" in note[0], notes
    assert not [p for p in props if p.rule == "homes"], "no house_dwarves: none can reach a free room"
    # all can reach: given rooms, nothing dug (as before)
    props, notes = [], []
    PH._homes_rules(homes_state(rooms_reachable=7), PLANNER_CONFIG, {}, props, notes)
    assert [p.rule for p in props if p.rule in ("homes", "homes_dig")] == ["homes"], [p.rule for p in props]
    # some reach: the rest dug for
    props, notes = [], []
    PH._homes_rules(homes_state(rooms_reachable=3), PLANNER_CONFIG, {}, props, notes)
    dig = [p for p in props if p.rule == "homes_dig"]
    assert dig and dig[0].action["rooms"] == 4 + PLANNER_CONFIG["min_spare_beds"], [(p.rule, p.action) for p in props]


@test("homes census: the free bedrooms' levels no roomless household reaches (free_cut_z)")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    src = (ROOT / "tests" / "test_homes.py").read_text(encoding="utf-8")
    fake = re.search(r'FAKE = r"""(.*?)"""', src, re.S).group(1)
    L = LuaRuntime(unpack_returned_tuples=True)

    def lt(v):
        if isinstance(v, dict):
            return L.table_from({k: lt(x) for k, x in v.items()})
        if isinstance(v, (list, tuple)):
            return L.table_from([lt(x) for x in v])
        return v
    bed = [{"v": 10}]
    env, _, _ = L.execute(fake, module_src("ai-homes.lua"), lt({"units": [{"id": 1, "far": True}],
                                                               "zones": [{"id": 10, "items": bed}]}))
    c = env.census()
    assert c.rooms_reachable == 0 and c.free_cut_z is not None and list(c.free_cut_z.values()) == [1], dict(c)
    env, _, _ = L.execute(fake, module_src("ai-homes.lua"), lt({"units": [{"id": 1}],
                                                               "zones": [{"id": 10, "items": bed}]}))
    c = env.census()
    assert c.rooms_reachable == 1 and c.free_cut_z is None, dict(c)


# --- 5. drunkenness --------------------------------------------------------------------

@test("syndromes: inebriation (unconsciousness among its effects) is neither listed nor deadly; a real one is (A7)")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    src = (ROOT / "tests" / "test_syndromes.py").read_text(encoding="utf-8")
    fake = re.search(r'FAKE = r"""(.*?)"""', src, re.S).group(1)
    L = LuaRuntime(unpack_returned_tuples=True)

    def T(d):
        if isinstance(d, dict):
            return L.table_from({k: T(v) for k, v in d.items()})
        if isinstance(d, list):
            return L.table_from([T(v) for v in d])
        return d
    env, w = L.execute(fake, module_src("ai-syndromes.lua"))
    w.syn(8, T({"syn_name": "inebriation", "flags": {"SYN_INGESTED": True},
                "effects": ["DIZZINESS", "UNCONSCIOUSNESS"]}))
    w.syn(6, T({"syn_name": "spider venom", "flags": {"SYN_INJECTED": True}, "effects": ["PARALYSIS"]}))
    for i in range(1, 4):
        w.unit(T({"id": i, "name": f"Drunk{i}", "syndromes": {"active": [{"type": 8, "ticks": 100}]}}))
    w.unit(T({"id": 9, "name": "Bitten", "syndromes": {"active": [{"type": 6, "ticks": 100}]}}))
    r = env.report()
    assert r.afflicted == 1 and r.deadly == 1 and r.drunk == 3, (r.afflicted, r.deadly, r.drunk)
    assert dict(r.by_name) == {"spider venom": 1}, dict(r.by_name)


@test("society: the health section's syndrome note leaves out inebriation and gives way to the syndromes section")
def _():
    def notes_of(s):
        notes = []
        PSo._people_rules(s, PLANNER_CONFIG, [], notes)
        return notes
    n = notes_of({"health": {"syndromes": 15, "syndrome_names": {"inebriation": 15}}})
    assert not [x for x in n if "syndrome" in x], n
    n = notes_of({"health": {"syndromes": 2, "syndrome_names": {"beast blight": 2}}})
    assert [x for x in n if "beast blight (2)" in x], n
    n = notes_of({"health": {"syndromes": 2, "infected": 1, "syndrome_names": {"beast blight": 2}},
                  "syndromes": {"list": [], "afflicted": 2}})
    assert not [x for x in n if "beast blight" in x] and [x for x in n if "1 citizens walk about" in x], n


# --- 6. deep_descent off --------------------------------------------------------------

@test("deep_descent: off in the planner config, in the Rules defaults, in no preset; on by the Rules switch")
def _():
    assert PLANNER_CONFIG["deep_descent"] is False
    st = lua_text("ai-overseer-settings.lua")
    assert re.search(r"^\s*deep_descent = false,", st, re.M), "Rules default"
    presets = st[st.index("BUILTIN_PRESETS = {"):st.index("-- (applied: an optional table")]
    assert "deep_descent" not in presets, "a preset names deep_descent"
    keys = st[st.index("PRESET_RULE_KEYS = {"):st.index("BUILTIN_PRESET_RULES = {")]
    assert "deep_descent" not in keys, "presets may set deep_descent"
    assert "deep_descent" not in player_rules({"settings": {}})     # (the strategist's Rules summary unchanged)
    assert not PD.descent_on({"settings": {}}, PLANNER_CONFIG)
    assert PD.descent_on({"settings": {"deep_descent": True}}, PLANNER_CONFIG)
    assert PD.descent_on({"settings": {}}, dict(PLANNER_CONFIG, deep_descent=True))


@test("deep_descent: the settings module keeps, sanitizes and sends the switch (lupa)")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    st = lua_text("ai-overseer-settings.lua")
    L = LuaRuntime(unpack_returned_tuples=True)
    ok, err = L.eval("function(s) local f, e = load(s, 'ai-overseer-settings', 't', {}); return f ~= nil, e end")(st)
    assert ok, err
    # its sanitize list and its export both name it
    assert re.search(r"'deep_descent',", st) and "deep_descent = s.deep_descent" in st


if __name__ == "__main__":
    finish()
