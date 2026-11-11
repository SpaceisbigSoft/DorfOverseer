"""(0.105.32, gatesplit) An open gate the game treats as shut (lua/ai-gates.lua).

E (8 Nov): the founding stair's hatch, on its lever, read open after two
instant pulls, but DF's walk map was split at it; every citizen outside was
stranded and reported as "no path", and 64 died of thirst. Checked here on a
fake map (walk groups per tile, a hatch with door_flags):

- the scan's report finds the split hatch (flags, tiles, link); an open hatch
  whose sides walk together, or one that reads shut, isn't flagged;
- a citizen in the split's outside group is stranded by "gate_stuck" (with
  the piece), one elsewhere still by "no path";
- unstick_gate's three steps and what each does; refused with an enemy near,
  while the cavern seal holds it, and (step 3) for the player's own piece;
  dry runs change nothing;
- the spot of a piece taken down is kept (and saved): no lever is linked to a
  new piece there for a year;
- after an instant pull that opens a hatch, a split is noted at once.

    python tests/test_r32_gatesplit.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from lua_modules_util import module_src  # noqa: E402
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

LUA = LuaRuntime(unpack_returned_tuples=True)


def K(x, y, z):
    return (z * 4096 + y) * 4096 + x


GAME = r"""
local src = ...
local G = {citizens = {}, units = {}, groups = {}, zones = {}, blds = {}, shapes = {}, saved = {},
           pulled = {}, removed = {}, traps = {}, join_on_pull = nil}
local e = setmetatable({G = G}, {__index = _G})
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
e.COLOR_GREEN, e.COLOR_YELLOW, e.CR_OK = 2, 14, 0
local TT = {[1] = 'StoneStairUD', [2] = 'StoneStairD', [3] = 'OpenSpace'}
e.df = {global = {cur_year = 250, cur_year_tick = 5000,
                  world = {units = {active = G.units}, reindex_pathfinding = false,
                           buildings = {other = {ZONE_MEETING_HALL = G.zones, TRAP = G.traps}}}},
        building = {find = function(id) return G.blds[id] end},
        building_type = {Trap = 'Trap', Hatch = 'Hatch', Door = 'Door', Bridge = 'Bridge'},
        trap_type = {Lever = 'Lever'},
        job_type = {PullLever = 'PullLever', LinkBuildingToTrigger = 'Link', DestroyBuilding = 'Destroy'},
        item_type = {TRAPPARTS = 'TRAPPARTS'},
        general_ref_type = {BUILDING_TRIGGER = 'BT', BUILDING_HOLDER = 'BH'},
        tiletype = TT}
e.dfhack = {units = {getCitizens = function() return G.citizens end,
                     getReadableName = function(u) return u.name end,
                     isAlive = function() return true end, isCitizen = function(u) return u.citizen == true end,
                     isHidden = function() return false end, isDanger = function(u) return u.danger == true end,
                     isInvader = function() return false end, isGreatDanger = function() return false end},
            maps = {getWalkableGroup = function(p) return G.groups[p.x .. ',' .. p.y .. ',' .. p.z] or 0 end,
                    getTileFlags = function(x, y, z) return {feature_global = false} end,
                    getTileType = function(x, y, z)
                        if z == 170 then return 1 elseif z == 171 then return 2 else return 3 end end},
            persistent = {getSiteData = function(k, d) return G.saved[k] or d end,
                          saveSiteData = function(k, v) G.saved[k] = v end},
            buildings = {deconstruct = function(b) table.insert(G.removed, b.id); return false end},
            gui = {showAnnouncement = function() end},
            timeout = function() return 1 end, timeout_active = function() return nil end}
assert(load(src, 'ai-gates', 't', e))()
-- the map's shapes, by tile (tile() is what the module reads them by)
e.tile = function(x, y, z) local s = G.shapes[x .. ',' .. y .. ',' .. z]; return s and {shape = s, walk = true} or nil end
e.seal_holds = function() return G.seal or {ids = {}, levers = {}} end
-- an instant pull toggles the hatch; G.join_on_pull: DF joins the walk map then
e.pull_instant = function(l)
    table.insert(G.pulled, l)
    local h = G.blds[7]
    h.door_flags.closed = not h.door_flags.closed
    if G.join_on_pull and not h.door_flags.closed then G.groups['108,149,171'] = G.join_on_pull end
    return true
end
return e
"""


def rig(*, player=False, closed=False, forbidden=False):
    """E's way in: entrance 1 (surface), its only gate the founding stair's
    hatch 7 at x108 y149 z171 over the stair at z170, on lever 137. The
    hatch's tile and the surface are walk group 5151, the stair and the fort
    1702 (the split)."""
    E = LUA.execute(GAME, module_src("ai-gates.lua"))
    G = E.G
    t = LUA.table_from
    G.shapes["108,149,170"] = "STAIR_UPDOWN"
    G.shapes["108,149,171"] = "STAIR_DOWN"
    for k, g in {"108,149,171": 5151, "108,149,170": 1702, "100,100,170": 1702,
                 "120,140,171": 5151, "60,60,150": 999}.items():
        G.groups[k] = g
    lever_name = "Lever" if player else "AI gate lever"
    lever = t({"id": 137, "name": lever_name, "trap_type": "Lever", "centerx": 100, "centery": 100, "z": 170,
               "linked_mechanisms": t([t({})]), "jobs": t([t({"job_type": "Link"})]),
               "getType": LUA.eval("function() return 'Trap' end"),
               "getBuildStage": LUA.eval("function() return 1 end"),
               "getMaxBuildStage": LUA.eval("function() return 1 end")})
    G.blds[137] = lever
    G.traps[1] = lever
    mech = t({"item": t({"general_refs": t([t({"building_id": 137,
                                                "getType": LUA.eval("function() return 'BT' end")})]),
                         "getType": LUA.eval("function() return 'TRAPPARTS' end")})})
    G.blds[7] = t({"id": 7, "x1": 108, "y1": 149, "x2": 108, "y2": 149, "z": 171, "close_timer": 0,
                   "door_flags": t({"closed": closed, "forbidden": forbidden, "operated_by_mechanisms": True,
                                    "pet_passable": False}),
                   "jobs": t({}), "contained_items": t([mech]),
                   "getType": LUA.eval("function() return 'Hatch' end"),
                   "getBuildStage": LUA.eval("function() return 1 end"),
                   "getMaxBuildStage": LUA.eval("function() return 1 end")})
    hatch = t({"id": 7, "kind": "hatch", "x1": 108, "y1": 149, "x2": 108, "y2": 149, "z": 171,
               "lever_driven": True, "lever_id": 137, "drive_lever": 137, "drive_ai": not player,
               "levers": t([t({"id": 137, "x": 100, "y": 100, "z": 170, "name": lever_name})])})
    ent = t({"id": 1, "kind": "surface", "x": 108, "y": 149, "z": 170,
             "inside_list": t([K(108, 149, 170)]), "outs": t({K(108, 149, 171): True}),
             "equipment": t([hatch]), "door_spots": t({})})
    inside = t({K(108, 149, 170): True, K(100, 100, 170): True})
    E.GATES = t({"scanned": True, "inside": inside, "entrances": t([ent]), "closed": t({})})
    E.GATES_SAVE = t({"restored": True, "persisted": t({})})
    # the report's other parts, not wanted here
    E.free_mechanism_count = LUA.eval("function() return 0 end")
    E.gate_parts = LUA.eval("function() return {} end")
    G.citizens[1] = t({"id": 1, "name": "Out", "pos": t({"x": 120, "y": 140, "z": 171})})
    G.citizens[2] = t({"id": 2, "name": "Lost", "pos": t({"x": 60, "y": 60, "z": 150})})
    G.citizens[3] = t({"id": 3, "name": "Home", "pos": t({"x": 100, "y": 100, "z": 170})})
    return E, G


def lst(t):
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


@test("a hatch that reads open with DF's walk map split at it: the report's split, with flags, tiles and link")
def _():
    E, G = rig()
    r = E.summary()
    e1 = r.entrances[1]
    sp = lst(e1.split)
    assert len(sp) == 1, sp
    p = sp[0]
    assert (p.id, p.kind, p.x, p.y, p.z) == (7, "hatch", 108, 149, 171)
    assert p.outside_group == 5151 and p.inside_group == 1702, (p.outside_group, p.inside_group)
    assert p.flags.closed is False and p.flags.forbidden is False and p.flags.operated_by_mechanisms is True
    assert p.flags.close_timer == 0 and p.flags.jobs == 0
    assert (p.tiles.above, p.tiles.at, p.tiles.below) == ("OpenSpace", "StoneStairD", "StoneStairUD")
    assert p.link.lever_id == 137 and p.link.linked_mechanisms == 1 and p.link.status == "linking"
    assert p.link.mechanisms == 1 and p.link.trigger_refs == 1
    assert p.since == 250 * 403200 + 5000, p.since
    # the scan's entrance record carries it too
    assert E.GATES.entrances[1].split[1].id == 7 and E.GATES.split_seen[7] is not None


@test("an open hatch whose sides walk together, or one that reads shut, is not flagged")
def _():
    E, G = rig()
    G.groups["108,149,171"] = 1702
    assert E.gate_splits() == 0 and E.GATES.entrances[1].split is None
    E, G = rig(closed=True)
    assert E.gate_splits() == 0
    E, G = rig(forbidden=True)
    assert E.gate_splits() == 0
    # a hatch over no stair joins nothing
    E, G = rig()
    G.shapes["108,149,170"] = "FLOOR"
    assert E.gate_splits() == 0


@test("stranded: gate_stuck (with the piece) only for the split's outside group; elsewhere still no_path")
def _():
    E, G = rig()
    r = E.stranded_citizens()
    rows = {row.name: row for row in lst(r.list)}
    assert set(rows) == {"Out", "Lost"}, set(rows)
    assert rows["Out"].cause == "gate_stuck" and rows["Out"].stuck_gate == 7 and rows["Out"].entrance.id == 1
    assert rows["Lost"].cause == "no_path" and rows["Lost"].stuck_gate is None
    # the walk map joined again: Out is in, Lost still out
    G.groups["108,149,171"] = 1702
    G.groups["120,140,171"] = 1702
    r = E.stranded_citizens()
    assert r.total == 1 and r.list[1].name == "Lost" and r.list[1].cause == "no_path"


@test("unstick step 1: unlocked, opened by its lever (it read shut), DF asked to redo its walk map; dry run changes nothing")
def _():
    E, G = rig(closed=True, forbidden=True)
    r = E.unstick_gate(7, 1, True)
    assert r.ok and r.dry_run and "would" in r.done, r.done
    assert len(G.pulled) == 0 and G.blds[7].door_flags.forbidden is True
    assert E.df["global"].world.reindex_pathfinding is False and r.split_after is None
    r = E.unstick_gate(7, 1, False)
    assert r.ok and r.step == 1 and lst(G.pulled) == [137], r.done
    assert G.blds[7].door_flags.forbidden is False and G.blds[7].door_flags.closed is False
    assert E.df["global"].world.reindex_pathfinding is True and r.reindexed
    assert r.flags_before.forbidden is True and r.flags_after.forbidden is False
    assert r.split_after is True and "unlocked" in r.done and "lever 137" in r.done
    # open and unlocked already: only the walk map asked again, no pull
    r = E.unstick_gate(7, 1, False)
    assert r.ok and lst(G.pulled) == [137] and "redo its walk map" in r.done


@test("unstick step 2: its lever pulled twice at once (shut, open); the walk map joined reads split_after false")
def _():
    E, G = rig()
    r = E.unstick_gate(7, 2, True)
    assert r.ok and len(G.pulled) == 0 and "would pull" in r.done
    G.join_on_pull = 1702
    r = E.unstick_gate(7, 2, False)
    assert r.ok and lst(G.pulled) == [137, 137] and r.pulls == 2, r.done
    assert G.blds[7].door_flags.closed is False and r.split_after is False
    # no lever of its own: refused
    E, G = rig()
    E.GATES.entrances[1].equipment[1].drive_lever = None
    r = E.unstick_gate(7, 2, False)
    assert not r.ok and r.rejected and "no lever" in r.error


@test("unstick step 3: the AI's hatch taken down, the spot kept (and saved); dry run changes nothing")
def _():
    E, G = rig()
    r = E.unstick_gate(7, 3, True)
    assert r.ok and "would take down the hatch at x108 y149 z171" in r.done, r.done
    assert len(G.removed) == 0 and E.GATES.stuck_removed is None
    assert "ai-overseer/gates" not in dict(G.saved)
    r = E.unstick_gate(7, 3, False)
    assert r.ok and lst(G.removed) == [7], r.done
    at = E.GATES.stuck_removed["108:149:171"]
    assert at == 250 * 403200 + 5000, at
    assert G.saved["ai-overseer/gates"].stuck_removed["108:149:171"] == at
    # the walk map joined (not stuck now): step 3 leaves it standing
    E, G = rig()
    G.groups["108,149,171"] = 1702
    r = E.unstick_gate(7, 3, False)
    assert not r.ok and r.rejected and "not stuck" in r.error and len(G.removed) == 0


@test("unstick refused with an enemy near, while the seal holds it; step 3 never takes the player's own piece")
def _():
    t = LUA.table_from
    E, G = rig(closed=True)
    G.units[1] = t({"id": 9, "danger": True, "pos": t({"x": 115, "y": 149, "z": 171}), "flags1": t({})})
    for step in (1, 2, 3):
        r = E.unstick_gate(7, step, False)
        assert not r.ok and r.rejected and "enemy" in r.error, r.error
    assert len(G.pulled) == 0 and len(G.removed) == 0 and G.blds[7].door_flags.closed is True
    G.units[1].pos.x = 140                      # 32 tiles off: no longer in the way
    assert E.unstick_gate(7, 1, False).ok
    E, G = rig(closed=True)
    G.seal = t({"ids": t({7: True}), "levers": t({})})
    for step in (1, 2, 3):
        r = E.unstick_gate(7, step, True)
        assert not r.ok and r.rejected and "seal" in r.error, r.error
    assert len(G.pulled) == 0 and G.blds[7].door_flags.closed is True
    E, G = rig(player=True)
    r = E.unstick_gate(7, 3, False)
    assert not r.ok and r.rejected and "player" in r.error and len(G.removed) == 0
    assert E.unstick_gate(7, 1, False).ok           # (steps 1 and 2 are harmless: allowed)
    r = E.unstick_gate(99, 1, False)
    assert not r.ok and r.rejected


@test("a spot where a stuck piece was taken down: no lever linked to a new piece there for a year; kept over a reload")
def _():
    t = LUA.table_from
    E, G = rig()
    assert E.unstick_gate(7, 3, False).ok
    # a new hatch built there by fortify: the AI's lever isn't linked to it
    r = E.link_lever(137, 7)
    assert not r.ok and r.rejected and r.stuck_spot, r.error
    r = E.place_gate_lever(1, True)
    assert not r.ok and r.rejected and r.stuck_spot, r.error
    # a reload: the record comes back from the save
    E.GATES = t({"scanned": False})
    E.GATES_SAVE = t({})
    E.gates_restore()
    assert E.stuck_spot(108, 149, 171) is not None
    E.GATES.scanned = True
    # a scan keeps it
    E.fort_starts = LUA.eval("function() return {} end")
    E.find_entrances = LUA.eval("function() return {}, {}, 0 end")
    E.cut_survey = LUA.eval("function() end")
    E.gate_buildings = LUA.eval("function() return {} end")
    E.scan(0)
    assert E.stuck_spot(108, 149, 171) is not None
    # a year on: the spot is free again
    E.df["global"].cur_year = 251
    E.df["global"].cur_year_tick = 6000
    assert E.stuck_spot(108, 149, 171) is None
    E2, G2 = rig()
    E2.GATES.stuck_removed = t({"108:149:171": 250 * 403200 + 5000})
    r = E2.link_lever(137, 7)
    assert r.stuck_spot                          # (the same year: still refused)
    E2.df["global"].cur_year, E2.df["global"].cur_year_tick = 251, 6000
    r = E2.link_lever(137, 7)
    assert not r.stuck_spot, r.error             # (refused later for other reasons in this fake, not the spot)


@test("after an instant pull that opens a hatch, a split is noted at once; a pull that joins the map is not")
def _():
    t = LUA.table_from
    E, G = rig(closed=True)
    assert E.open_lever_hatches() == 1 and lst(G.pulled) == [137]
    assert E.GATES.split_seen[7] == 250 * 403200 + 5000
    # the report then reads it itself (kept since then)
    E.df["global"].cur_year_tick = 7000
    E.gate_splits()
    assert E.GATES.entrances[1].split[1].since == 250 * 403200 + 5000
    E, G = rig(closed=True)
    G.join_on_pull = 1702
    assert E.open_lever_hatches() == 1 and E.GATES.split_seen is None
    # the saved gates opened straight from the save (before a scan)
    E, G = rig(closed=True)
    saved = t({"gates": t([t({"id": 7, "kind": "hatch", "drive_lever": 137})])})
    opened, waiting = E.open_saved_gates(saved)
    assert opened == 1 and E.GATES.split_seen[7] is not None
    # the pull that shuts it (the watcher closing) notes nothing
    E, G = rig()
    E.note_split_after_open(t({"kind": "hatch"}), G.blds[7])
    assert E.GATES.split_seen[7] is not None
    G.blds[7].door_flags.closed = True
    E.GATES.split_seen = None
    assert E.note_split_after_open(t({"kind": "hatch"}), G.blds[7]) is False


@test("bridge: unstick_gate is an action, its dry run allowed")
def _():
    src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "unstick_gate = act_unstick_gate" in src and "'unstick_gate'," in src
    acts = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    assert "function act_unstick_gate(a)" in acts


if __name__ == "__main__":
    finish()
