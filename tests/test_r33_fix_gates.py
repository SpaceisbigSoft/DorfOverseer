"""(0.105.33 fix, gates) The round-33 verifier's gates findings, fixed:

- the stranded rule's open_gates is held only by a siege at the gates
  (invaders, a great danger, a held-off threat near a gate the AI shut), not
  by a wild animal far out on the surface;
- note_gate_lever leaves out a gatehouse's outer drawbridge lever, as
  _military_rules does (one shared watched_gate_levers);
- gates_snapshot leaves out an entrance being opened (its pull survives a reload);
- a bone or shell mood (or bones at the reserve) takes usable parts off
  deteriorate's timer (prune_remains keep).

    python tests/test_r33_fix_gates.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import planner  # noqa: E402
from planner import Memory, plan, PLANNER_CONFIG  # noqa: E402
import planner_industry  # noqa: E402

FIX = json.loads((ROOT / "tests/fixtures/test_fort.json").read_text())


def stranded_state(threat):
    s = json.loads(json.dumps(FIX))
    ent = s["entrances"]
    ent["armed"] = True
    ent["entrances"] = [{"id": 2, "kind": "surface", "x": 150, "y": 20, "z": 173, "width": 1, "sealed": True,
                         "closed": True, "equipment": [{"id": 501, "kind": "door"}], "door_spots": 0}]
    ent["stranded"] = [{"id": 70 + i, "name": f"Urist {i}", "x": 152, "y": 18, "z": 173, "cause": "lockdown",
                        "by_ai": True, "out_ticks": 2400, "out_days": 2, "danger_near": 150, "gate_danger": 150,
                        "entrance": {"id": 2, "kind": "surface", "x": 150, "y": 20, "z": 173}} for i in range(2)]
    s["others_on_map"]["threats"] = [dict({"id": 901, "name": "giant badger", "invader": False,
                                           "can_reach_dwarves": False, "layer": "upper_levels",
                                           "distance_to_nearest_dwarf": 150, "kinds": []}, **threat)]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    return s


def opens(s):
    props, notes = plan(s, Memory())
    return ([p.action.get("type") for p in props if p.rule == "stranded"],
            [n for n in notes if "shut outside" in n])


@test("stranded: a far wild animal doesn't keep the AI's lockdown shut on citizens (open_gates, as main)")
def _():
    for extra in ({}, {"pos": {"x": 10, "y": 150, "z": 173}}):
        got, notes = opens(stranded_state(extra))
        assert got == ["open_gates"] and not notes, (extra, got, notes)


@test("stranded: an invader held off, a great danger, or a wild one at a shut gate: never open_gates; their gate alone or a wait")
def _():
    for extra in ({"invader": True, "pos": {"x": 10, "y": 150, "z": 173}},
                  {"great_danger": True, "pos": {"x": 10, "y": 150, "z": 173}},
                  {"pos": {"x": 150, "y": 45, "z": 173}},          # 25 tiles off the AI-shut gate
                  {"distance_to_nearest_dwarf": 12}):              # unplaced, close to a dwarf
        got, notes = opens(stranded_state(extra))
        # (0.105.34) the AI opens their gate alone, or says it waits for the enemy
        # to move off: never open_gates, never a question for the player
        assert "open_gates" not in got, (extra, got, notes)
        assert got == ["open_entrance"] or (notes and "keeps it shut" in notes[0]), (extra, got, notes)


@test("note_gate_lever: the watcher's outer drawbridge lever is not the AI gate (no pull of the other lever)")
def _():
    s = json.loads(json.dumps(FIX))
    s["entrances"]["entrances"] = [{"id": 1, "kind": "surface", "x": 150, "y": 20, "z": 173, "width": 1,
                                    "sealed": True, "door_spots": 0,
                                    "equipment": [{"id": 500, "kind": "bridge", "lever_id": 60, "levers": [60]}],
                                    "outer": [{"id": 501, "kind": "bridge", "lever_id": 77}]}]
    s.setdefault("military", {})["gates"] = [
        {"id": 77, "name": "AI gate", "linked": True, "pending": False, "state": 0},
        {"id": 78, "name": "AI gate 2", "linked": True, "pending": False, "state": 0}]
    s["others_on_map"]["threats"] = []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    assert planner.watched_gate_levers(s) == {60, 77}
    m = Memory()
    m.quiet_cycles = 50
    planner.note_gate_lever(s, m)
    s["military"]["gates"][0]["state"] = 1          # the watcher raised the outer bridge
    planner.note_gate_lever(s, m)
    assert m.gate_closed_by_ai is False and "77" not in m.gate_open_state, (m.gate_closed_by_ai, m.gate_open_state)
    props, _ = plan(s, m)
    assert not [p for p in props if p.action.get("type") == "pull_gate"]


@test("gates_snapshot: an entrance being opened is not saved as closed; a closed one still is")
def _():
    L = LuaRuntime(unpack_returned_tuples=True)
    M = L.execute(r"""
local src = ...
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-gates', 't', env))()
return env""", module_src("ai-gates.lua"))
    L.execute(r"""
local M = ...
M.stuck_removed_live = function() return {} end
M.GATES = {armed = true, peak = 0, closed = {[1] = true, [2] = true}, opening = {[1] = true},
  entrances = {{id = 1, equipment = {{id = 40, kind = 'bridge', lever_id = 91}}},
               {id = 2, equipment = {{id = 50, kind = 'bridge', lever_id = 92}}}}}
""", M)
    snap = M.gates_snapshot()
    assert [g.id for g in snap.gates.values()] == [50], list(snap.gates.values())


@test("prune: a bone mood or bones at the reserve, after a prune, takes usable parts off the timer")
def _():
    s = json.loads(json.dumps(FIX))
    s["needs"] = dict(s.get("needs") or {}, bones=2)
    m = Memory()
    props = []
    planner_industry._clutter_rules(s, PLANNER_CONFIG, props, [], m)
    assert not [p for p in props if p.rule == "prune_keep_parts"], "never pruned: nothing to take off"
    m.last_fired["prune"] = 0
    props = []
    planner_industry._clutter_rules(s, PLANNER_CONFIG, props, [], m)
    got = [p.action for p in props if p.rule == "prune_keep_parts"]
    assert got == [{"type": "prune_remains", "keep": ["usable-parts"]}], got
    s["needs"]["bones"] = 50
    s["moods"] = {"list": [{"missing": [{"item": "NONE", "flags": ["bone"]}]}]}
    props = []
    planner_industry._clutter_rules(s, PLANNER_CONFIG, props, [], m)
    assert [p for p in props if p.rule == "prune_keep_parts"], "a bone mood"
    s["moods"] = {"list": []}
    props = []
    planner_industry._clutter_rules(s, PLANNER_CONFIG, props, [], m)
    assert not [p for p in props if p.rule == "prune_keep_parts"]


@test("prune_remains keep: only 'deteriorate disable usable-parts', nothing enabled, no corpse pass")
def _():
    harness_src = re.search(r'HARNESS = r"""(.*?)"""',
                            (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8"), re.S).group(1)
    L = LuaRuntime(unpack_returned_tuples=True)
    H = L.execute(harness_src, (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8"), str(ROOT / "lua"))
    env = H.module()
    ok, cmds, kept, dry = L.execute(r"""
local env, H = ...
H.cmds = {}
H.dfhack.findScript = function() return '/df/hack/scripts/deteriorate.lua' end
H.dfhack.run_command_silent = function(...) table.insert(H.cmds, table.concat({...}, ' ')); return 'ok', 0 end
env.get_dead = function() return {unburied = 0} end
local r = env.act_prune_remains({keep = {'usable-parts', 'corpses'}})
local d = env.act_prune_remains({keep = {'usable-parts'}, dry_run = true})
return r.ok, table.concat(H.cmds, '|'), table.concat(r.kept, ','), d.dry_run
""", env, H)
    assert ok and cmds == "deteriorate disable usable-parts" and kept == "usable-parts" and dry, (ok, cmds, kept)


if __name__ == "__main__":
    sys.exit(finish())
