"""(item3, the player's yes 25 Nov 22:38) The guarded cavern way: one way of
the AI's from the fort onto the first cavern's floor (a stair and a straight
tunnel, a plain door at its cavern end, a hatch on a lever as its gate, kept
shut), opened only for a job while no danger is near.

Tested here: lua/ai-cavern-way.lua's pure plan (lupa: run on the PC), the
action, the section and the Rules switch wired into the bridge, the seal's
and the lure's and the gates scan's use of the way, and the brain's rule
(brain/planner_cavern_way.py): when it is built, opened (silk, a hunt, the
lure's builders, cavern trees, a stranded citizen) and shut (a danger, the
job done, too long open, the switch off), "gates close late", the seal.

    python tests/test_item3_cavern_way.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
from planner_core import LIMIT_EXEMPT, STEER_PROTECTED, player_rules, TICKS_PER_DAY  # noqa: E402
import planner_cavern_way as CW  # noqa: E402
import hold_classes  # noqa: E402
import overseer_words  # noqa: E402
from digest import SECTION_DEFAULTS  # noqa: E402

LUA_DIR = ROOT / "lua"
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(PLANNER_CONFIG)


def lua(name: str) -> str:
    return (LUA_DIR / name).read_text(encoding="utf-8")


DOOR = {"x": 40, "y": 20, "z": 100, "elevation": -30}
READY = {"state": "ready", "layer": "Cavern1", "top": {"x": 30, "y": 20, "z": 120, "elevation": -10},
         "door": DOOR, "out": {"x": 41, "y": 20, "z": 100}, "gate": "closed", "linked": True,
         "lever_id": 7, "hatch_id": 8, "door_id": 9, "dangers": [], "beyond": 0, "webs": 0}


def state(way=None, **kw) -> dict:
    s = {"date": {"year": 260, "tick": 50_000, "season": "spring"}, "dwarves": {"total": 40},
         "settings": {}, "buildings": {"workshops": {}}, "others_on_map": {}, "deep": {}, "threats": {},
         "lures": {"lures": [], "candidates": []}}
    if way is not None:
        s["cavern_way"] = way
    for k, v in kw.items():
        s[k] = v
    return s


def run(s, memory=None):
    props, notes = [], []
    CW._cavern_way_rule(s, CFG, props, notes, memory if memory is not None else Memory())
    return props, notes


def way(**kw) -> dict:
    w = copy.deepcopy(READY)
    w.update(kw)
    return w


SILK = {"supplies": {"cloth_kinds": {"silk": 0}}, "buildings": {"workshops": {"Loom": 1}}}


def silky(w, **kw):
    return state(w, **dict(SILK, **kw))


# --- the bridge ------------------------------------------------------------------------


@test("bridge: the action, its dry run, its halted shut, the section in the pulse, the module listed")
def _():
    cat = lua("ai-bridge-catalog.lua")
    assert "cavern_way = function(a)" in cat and "reqscript('ai-cavern-way')" in cat
    assert "'cavern_way',     -- (item3)" in cat
    assert "cavern_way = 'release_only'" in cat
    sec = lua("ai-bridge-sections.lua")
    assert "cavern_way = function() return safe(function() return reqscript('ai-cavern-way').report(get_layers())" in sec
    pulse = sec[sec.index("PULSE_SECTIONS = {"):]
    assert "'cavern_way'," in pulse[:pulse.index("}")]
    assert "'ai-cavern-way'," in lua("ai-bridge.lua")
    assert "cavern_way" in SECTION_DEFAULTS
    assert "--@ module = true" in lua("ai-cavern-way.lua")


@test("the seal, the lure and the gates scan know the way: its door on the openings record, its hatch its own")
def _():
    sv = lua("ai-threats-survey.lua")
    assert "reqscript('ai-cavern-way').door_opening()" in sv and "'cavern way door'" in sv
    assert "reqscript('ai-cavern-way').own_keys()" in lua("ai-gates-scan.lua")
    lu = lua("ai-lure.lua")
    assert "is_way_door(b.id)" in lu and "reqscript('ai-cavern-way').door_opening()" in lu
    cw = lua("ai-cavern-way.lua")
    # the door is a plain door (the lure refuses a door on a lever); the gate is the hatch on the lever
    assert "G.link_lever" not in cw and "gates().link_lever(st.lever.id, st.hatch.id, false)" in cw
    # own_keys: ai-gates' own key
    assert "(t.z * 4096 + t.y) * 4096 + t.x" in cw


@test("the way is built safe: the breach waits for the linked gate, no danger, a door in store; the watcher shuts it")
def _():
    cw = lua("ai-cavern-way.lua")
    b = cw[cw.index("elseif st.state == 'breach' then"):cw.index("elseif st.state == 'door' then")]
    assert "sealed()" in b and "dangers_near(plan.out, BREACH_CLEAR)" in b and "free_doors() < 1" in b
    assert b.index("free_doors") < b.index("qf_try('dig'")
    # status: the breach only once the hatch is linked to the lever
    st = cw[cw.index("function status(d)"):cw.index("local function free_doors")]
    assert st.index("out.linked") < st.index("'breach'")
    # every cell but the door's dug first
    assert "c.part ~= 'door' and cell_state(read, c) == 'open'" in cw
    w = cw[cw.index("function watch_verdict"):cw.index("local function watch_tick")]
    assert "CLOSE_TILES" in w and "WATCH_NEAR" in w and "out_n" in w
    assert "CLOSE_TILES = 12" in cw and "WATCH_NEAR = 20" in cw


@test("sizes: every Lua file under 60 KB, planner.py under 92,000 bytes")
def _():
    for f in ("ai-cavern-way.lua", "ai-bridge-catalog.lua", "ai-bridge-sections.lua", "ai-threats-survey.lua",
              "ai-gates-scan.lua", "ai-lure.lua", "ai-overseer-settings.lua", "gui/ai-overseer-rules.lua"):
        assert (LUA_DIR / f).stat().st_size < 60_000, f
    assert (ROOT / "brain" / "planner.py").stat().st_size < 92_000


# --- the Rules switch --------------------------------------------------------------------


@test("settings: cavern_way on by default, sent to the AI, on the Rules tab (row 5, right of Spare convicts)")
def _():
    st = lua("ai-overseer-settings.lua")
    assert "        cavern_way = true," in st and "'cavern_way'," in st and "cavern_way = s.cavern_way," in st
    gui = lua("gui/ai-overseer-rules.lua")
    assert "view_id = 'cavern_way'" in gui and "frame = {t = 5, l = 98, w = 20}" in gui
    assert "self.subviews.cavern_way:setOption(s.cavern_way ~= false, false)" in gui
    m = re.search(r"view_id = 'cavern_way',.*?label = '((?:[^'\\]|\\.)*)',\s*label_width = (\d+)", gui, re.S)
    assert m and len(m.group(1)) < int(m.group(2)) and int(m.group(2)) + 4 <= 20
    assert player_rules({"settings": {}})["cavern_way"] is True
    assert player_rules({})["cavern_way"] is True
    assert player_rules({"settings": {"cavern_way": False}})["cavern_way"] is False


# --- the classes, the words ------------------------------------------------------------


@test("classes and words: build/open wait in a crisis, the shut always goes; a label for the action")
def _():
    assert hold_classes.RULE_CLASS["cavern_way_build"] == hold_classes.EXPANSION
    assert hold_classes.RULE_CLASS["cavern_way_open"] == hold_classes.EXPANSION
    assert hold_classes.RULE_CLASS["cavern_way_shut"] == hold_classes.DEFENCE
    assert "cavern_way_shut" in LIMIT_EXEMPT and "cavern_way_shut" in STEER_PROTECTED
    assert "cavern_way" in overseer_words.SHORT_WORDS
    props, _ = run(state(way(gate="open", open_for="silk")))
    shut = [p for p in props if p.rule == "cavern_way_shut"]
    assert shut and hold_classes.step_class(shut[0]) != hold_classes.EXPANSION


# --- building --------------------------------------------------------------------------


@test("build: a grown fort with no way gets the first step; a young or small one, a threat, a seal: none")
def _():
    props, _ = run(state({"state": "none"}))
    assert [p.rule for p in props] == ["cavern_way_build"], props
    a = props[0].action
    assert a["type"] == "cavern_way" and a["step"] == "build" and "caution" in a and "unfound_ok" in a
    assert not run(state({"state": "none"}, dwarves={"total": 12}))[0]
    assert not run(state({"state": "none"}, settings={"cavern_way": False}))[0]
    assert not run(state({"state": "none"}, others_on_map={"threats_that_can_reach_dwarves": [{"id": 1}]}))[0]
    assert not run(state({"state": "none"}, threats={"sealed": {"all caverns": {"tick": 1}}}))[0]
    # an unfound cavern only when the Rules' open_caverns allow it
    assert run(state({"state": "none"}, settings={"open_caverns": "always"}))[0][0].action["unfound_ok"] is True
    assert run(state({"state": "none"}, settings={"open_caverns": "never"}))[0][0].action["unfound_ok"] is False


@test("build: placed by the fort's character (Caution 50+ keeps it from the homes); a refusal is said, not retried")
def _():
    props, _ = run(state({"state": "none"}, settings={"traits": {"caution": 80}}))
    assert props and props[0].action["caution"] == 80 and "away from the homes" in props[0].reason
    cw = lua("ai-cavern-way.lua")
    assert "cautious and homes[z]" in cw
    props, notes = run(state({"state": "refused", "why": "no straight way", "retry_ticks": 5 * TICKS_PER_DAY}))
    assert not props and any("no cavern way: no straight way" in n for n in notes)


@test("build: each next step proposed; a step under way (digging, linking...) waits; a danger shuts an open gate")
def _():
    for st in ("dig", "lever", "hatch", "link", "breach", "door"):
        props, _ = run(state(way(state=st, gate=None)))
        assert [p.action.get("step") for p in props] == ["build"], (st, props)
    for st in ("digging", "lever_building", "hatch_building", "linking", "breaching", "door_building"):
        assert not run(state(way(state=st, gate=None)))[0], st
    props, _ = run(state(way(state="door_building", gate="open", dangers=[{"id": 5, "name": "a crundle", "d": 6}])))
    assert [p.rule for p in props] == ["cavern_way_shut"]


# --- opening ---------------------------------------------------------------------------


@test("silk: webs on the cavern side, a Loom and silk wanted: the gate opens; no webs, no Loom: it stays shut")
def _():
    props, _ = run(silky(way(webs=300)))
    assert [p.rule for p in props] == ["cavern_way_open"] and props[0].action == {
        "type": "cavern_way", "step": "open", "why": "silk"}, props
    assert not run(silky(way(webs=0)))[0]
    assert not run(state(way(webs=300), supplies={"cloth_kinds": {"silk": 0}}))[0]
    assert not run(silky(way(webs=300), settings={"cavern_way": False}))[0]


@test("danger: a hostile near the door, enemies inside, a great beast in the caverns (seal on): stays shut")
def _():
    props, notes = run(silky(way(webs=300, dangers=[{"id": 3, "name": "a giant cave spider", "d": 20}])))
    assert not props and any("giant cave spider" in n for n in notes)
    assert run(silky(way(webs=300, dangers=[{"id": 3, "name": "a giant cave spider", "d": 30}])))[0]
    assert not run(silky(way(webs=300), others_on_map={"threats_that_can_reach_dwarves": [{"id": 1}]}))[0]
    fb = {"dangers": [{"id": 9, "name": "Ruthless the Forgotten Beast", "layer": "Cavern1"}]}
    props, notes = run(silky(way(webs=300), deep=fb))
    assert not props and any("Forgotten Beast" in n for n in notes)
    # unseen in the way's layer counts too
    unseen = {"unseen": [{"id": 9, "kind": "forgotten beast", "layer": "Cavern1", "name": "Mishos"}]}
    assert not run(silky(way(webs=300), deep=unseen))[0]
    # the Rules' seal_caverns off: the player lets it open (the near-door test still holds)
    assert run(silky(way(webs=300), deep=fb, settings={"seal_caverns": False}))[0]
    assert not run(silky(way(webs=300), threats={"sealed": {"Cavern1": {"tick": 1}}}))[0]
    # a lure holding the door open, the door locked by the seal: shut
    lure = {"lures": [{"key": "40,20,100", "phase": "open", "open": True}]}
    assert not run(silky(way(webs=300), lures=lure))[0]
    assert not run(silky(way(webs=300, door_locked=True)))[0]


@test("lure: a pocket being built behind the way's door opens the stair for its builders, the door locked")
def _():
    lure = {"lures": [{"key": "40,20,100", "phase": "building"}], "beasts": [{"id": 9, "name": "Ruthless"}]}
    fb = {"dangers": [{"id": 9, "name": "Ruthless", "layer": "Cavern1"}]}
    props, _ = run(state(way(door_locked=True), lures=lure, deep=fb, threats={"sealed": {"Cavern1": {}}}))
    assert [p.action.get("why") for p in props] == ["lure"], props
    assert not run(state(way(door_locked=False), lures=lure, deep=fb))[0]
    assert not run(state(way(door_locked=True, dangers=[{"id": 9, "name": "Ruthless", "d": 5}]), lures=lure))[0]


def abs_now():
    from planner_core import abs_tick
    return abs_tick(state())


def hunt_section(region="cavern", route=None, great=False, hunts=None):
    return {"targets": [{"id": 77, "name": "a cave crocodile", "region": region, "layer": "Cavern1",
                         "route": route or {"ok": False, "blocked_by": "no_path"}, "great_danger": great}],
            "squads": [{"id": 1, "name": "The Axes", "soldiers": 5, "armed": 5, "at_home": True, "hunting": None,
                        "power": 50}],
            "hunts": hunts or [], "history": []}


@test("hunt: a cavern target the hunt can't reach (not a great danger) and a free squad: the gate opens for it")
def _():
    props, _ = run(state(way(), hunt=hunt_section()))
    assert [p.action.get("why") for p in props] == ["hunt"], props
    assert not run(state(way(), hunt=hunt_section(great=True)))[0]
    assert not run(state(way(), hunt=hunt_section(region="surface")))[0]
    assert not run(state(way(), hunt=hunt_section(route={"ok": False, "blocked_by": "seal"})))[0]
    assert not run(state(way(), hunt=hunt_section(), settings={"hunt": "off"}))[0]
    # the hunted target itself near the door doesn't keep the gate shut
    near = [{"id": 77, "name": "a cave crocodile", "d": 8}]
    assert run(state(way(dangers=near), hunt=hunt_section()))[0]
    # open while the hunt goes on
    h = hunt_section(route={"ok": True}, hunts=[{"squad_id": 1, "target_id": 77}])
    props, notes = run(state(way(gate="open", open_for="hunt", opened_tick=abs_now()), hunt=h))
    assert not props and any("open for a hunt" in n for n in notes), (props, notes)


@test("logging: wood short, few surface trees, cavern trees standing: opened; the switch off: not")
def _():
    f = {"cavern": {"trees": 40, "reachable": 0}, "surface": {"trees": 3}, "grove": {}, "ai_marked": 0}
    s = state(way(), forestry=f, stocks={"wood": 0})
    props, _ = run(s)
    assert [p.action.get("why") for p in props] == ["logging"], props
    s = state(way(), forestry=f, stocks={"wood": 0}, settings={"cavern_logging": False})
    assert not run(s)[0]
    # trees another way reaches already: no need to open this one
    f2 = dict(f, cavern={"trees": 40, "reachable": 12})
    assert not run(state(way(), forestry=f2, stocks={"wood": 0}))[0]


@test("stranded: a citizen beyond the shut gate and no danger: opened to let them back")
def _():
    props, _ = run(state(way(beyond=1, beyond_first="Urist")))
    assert [p.action.get("why") for p in props] == ["stranded"]
    assert not run(state(way(beyond=1, dangers=[{"id": 2, "name": "a troll", "d": 10}])))[0]


# --- shutting --------------------------------------------------------------------------


@test("shut: a danger within 12 shuts it whoever is out; within 25 only once nobody is beyond (gates close late)")
def _():
    t = abs_now()
    open_silk = dict(gate="open", open_for="silk", opened_tick=t, webs=300)
    props, _ = run(silky(way(**open_silk, dangers=[{"id": 2, "name": "a troll", "d": 8}], beyond=2)))
    assert [p.rule for p in props] == ["cavern_way_shut"] and props[0].priority == 0
    props, notes = run(silky(way(**open_silk, dangers=[{"id": 2, "name": "a troll", "d": 18}], beyond=1,
                                 beyond_first="Urist")))
    assert not props and any("stays open while Urist" in n for n in notes), notes
    props, _ = run(silky(way(**open_silk, dangers=[{"id": 2, "name": "a troll", "d": 18}], beyond=0)))
    assert [p.rule for p in props] == ["cavern_way_shut"]
    # a lure opened its door: the stair shut at once
    lure = {"lures": [{"key": "40,20,100", "phase": "open", "open": True}]}
    props, _ = run(silky(way(**open_silk), lures=lure))
    assert [p.rule for p in props] == ["cavern_way_shut"]


@test("shut: the job done, the switch off (nobody out), open too long (that job rests)")
def _():
    t = abs_now()
    props, _ = run(state(way(gate="open", open_for="silk", opened_tick=t)))
    assert [p.rule for p in props] == ["cavern_way_shut"] and "done" in props[0].reason
    props, _ = run(silky(way(gate="open", open_for="silk", opened_tick=t, webs=300), settings={"cavern_way": False}))
    assert [p.rule for p in props] == ["cavern_way_shut"]
    m = Memory()
    old = t - 4 * TICKS_PER_DAY
    props, _ = run(silky(way(gate="open", open_for="silk", opened_tick=old, webs=300)), m)
    assert [p.rule for p in props] == ["cavern_way_shut"] and "rests" in props[0].reason
    props, notes = run(silky(way(webs=300)), m)
    assert not props and any("rests" in n for n in notes)


@test("open: not again within half a day of a danger at its door")
def _():
    m = Memory()
    run(silky(way(webs=300, dangers=[{"id": 2, "name": "a troll", "d": 10}])), m)
    props, notes = run(silky(way(webs=300)), m)
    assert not props and any("a while" in n for n in notes)


@test("the whole planner: a fort with a ready way and silk wanted proposes the open; without the section nothing")
def _():
    s = copy.deepcopy(BASE)
    s["cavern_way"] = way(webs=300)
    s.setdefault("buildings", {}).setdefault("workshops", {})["Loom"] = 1
    s.setdefault("supplies", {})["cloth_kinds"] = {"silk": 0}
    props = plan(s, Memory())[0]
    assert [p.action.get("why") for p in props if p.rule.startswith("cavern_way")] == ["silk"], props
    s2 = copy.deepcopy(BASE)
    s2.pop("cavern_way", None)
    assert not [p for p in plan(s2, Memory())[0] if p.rule.startswith("cavern_way")]


# --- the Lua plan (lupa) ---------------------------------------------------------------

HARNESS = r"""
local src = ...
local env = setmetatable({reqscript = function() return {} end}, {__index = _G})
assert(load(src, 'ai-cavern-way', 't', env))()
local tiles = {}
local function k(x, y, z) return x .. ',' .. y .. ',' .. z end
local function read(x, y, z) return tiles[k(x, y, z)] or {shape = 'WALL', material = 'STONE'} end
local function fort() tiles = {}; for x = 10, 15 do for y = 10, 15 do tiles[k(x, y, 20)] = {shape = 'FLOOR', material = 'STONE'} end end end
local function cave(x0) for x = x0, 60 do for y = 0, 30 do
    tiles[k(x, y, 5)] = {shape = 'FLOOR', material = 'STONE', feature = true}
    for z = 6, 8 do tiles[k(x, y, z)] = {shape = 'EMPTY', material = 'AIR', feature = true} end end end end
local layer = {name = 'Cavern1', z_top = 8, z_bottom = 2}
local out = {}
fort(); cave(30)
local p = env.plan_way(read, nil, {{x = 12, y = 12, z = 20}, {x = 14, y = 11, z = 20}}, layer, {})
out.top_x, out.door_x, out.out_x, out.bottom, out.len = p.top.x, p.door.x, p.out.x, p.bottom_z, p.length
local cells = env.plan_cells(p)
out.first, out.last = cells[1].text, cells[#cells].part
fort(); cave(18)
out.short = env.plan_way(read, nil, {{x = 12, y = 12, z = 20}}, layer, {}) == nil
fort(); cave(30); tiles[k(13, 12, 10)] = {shape = 'FLOOR', material = 'STONE', liquid = true}
out.water = env.plan_way(read, nil, {{x = 12, y = 12, z = 20}}, layer, {}) == nil
fort(); cave(30); tiles[k(20, 13, 5)] = {shape = 'FLOOR', material = 'STONE', feature = true}
out.side = env.plan_way(read, nil, {{x = 12, y = 12, z = 20}}, layer, {}) == nil
fort(); cave(30); tiles[k(20, 12, 6)] = {shape = 'EMPTY', material = 'AIR'}
out.above = env.plan_way(read, nil, {{x = 12, y = 12, z = 20}}, layer, {}) == nil
fort(); cave(30)
local g, why = env.plan_way(read, function(x, y, z) if z == 9 then return 'adamantine' end end, {{x = 12, y = 12, z = 20}}, layer, {})
out.guard = g == nil and why:find('dig guard') ~= nil
fort(); cave(30)
local S = {{x = 12, y = 12, z = 20}, {x = 14, y = 11, z = 20}}
local b1, _w1, n1 = env.plan_way(read, nil, S, layer, {deadline = os.clock() - 1})
local b2, _w2, n2 = env.plan_way(read, nil, S, layer, {deadline = os.clock() - 1, from = n1, best = b1})
out.resume = n1 == 2 and b1.top.x == 12 and n2 == nil and b2.top.x == 14
out.v12 = env.watch_verdict({{d = 10}}, 3) ~= nil
out.v15 = env.watch_verdict({{d = 15}}, 1) == nil
out.v15b = env.watch_verdict({{d = 15}}, 0) ~= nil
out.v30 = env.watch_verdict({{d = 30}}, 0) == nil
return out
"""


@test("lua plan_way: the shortest straight way through solid rock; refused by water, a side opening, open air "
      "over the tunnel, the dig guard, a cavern too near for a pocket; a search spread over calls; the watcher's verdict")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    rt = LuaRuntime(unpack_returned_tuples=True)
    r = rt.execute(HARNESS, lua("ai-cavern-way.lua"))
    assert r["top_x"] == 14 and r["door_x"] == 29 and r["out_x"] == 30 and r["bottom"] == 5 and r["len"] == 15
    assert r["first"] == "j" and r["last"] == "door"
    for k in ("short", "water", "side", "above", "guard", "resume", "v12", "v15", "v15b", "v30"):
        assert r[k] is True, k


if __name__ == "__main__":
    finish()
