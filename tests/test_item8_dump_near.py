"""(item8) What DF dumped beside a garbage dump zone, and burial_others' churn (fort B).

Live 24 Nov 22:23, B: dump zone 228 (3x3 at x99-101 y157-159, level 170)
held no item (disposal.dump_zones[0].items 0) while 107 lay on the ramp
just below its corner (x98 y156, level 169) and 26 more on three ramps
beside it, outside every zone and stockpile. 31 DumpItem jobs pointed at
the zone's tiles; two minutes later 25 were gone and no item had moved,
and the 37 bodies burial_others had unforbidden and marked lay forbidden
and unmarked again (what DF dumps lands forbidden). So burial_others
marked them again every cooldown from 22:13 (34, 15, 14, 24, 27, 37, 7, 2,
11 bodies). Earlier, "cancels Dump item: Drop-off inaccessible" (10 in
the reports). A dwarf on a ramp a level below a dump tile is next to it:
DF ends the job there and leaves the item on the ramp.

Now: the disposal report counts what lies beside each zone (near_items,
near_unmarked, near_dumped) and the ramps at its edge (ramp_edge); beside a
flat dump the refuse is marked again (disposal_dump_near, mark_dump near),
beside a ramp's edge the dump is moved to flat ground (disposal_move_dump,
place_dump move) and the destroy step takes what DF left there (empty_dump
near); neither burial_others nor the junk marking marks what lies beside a
ramp-edged dump (ai-disposal left_beside, the dead report's
why.not_ours_beside). New dumps are placed flat (find_surface_rect flat).

And burial_others' own count: B's dead.why at 22:22 had not_ours 2 and no
not_ours_loose (both bodies marked, so the count was never set), which the
brain reads as a bridge before 0.105.51 and so asked with not_ours (2) each
cooldown; the action then marked the other bodies DF had dropped back. The
dead report now says not_ours_loose 0.

    python tests/test_item8_dump_near.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua, code_has  # noqa: E402
from lua_modules_util import bridge_part_src  # noqa: E402

from planner import Memory, PLANNER_CONFIG  # noqa: E402
from planner_core import player_rules  # noqa: E402
from planner_industry import _disposal_rules  # noqa: E402
import planner_welfare as W  # noqa: E402

CFG = PLANNER_CONFIG
LUA = ROOT / "lua"
DISPOSAL = (LUA / "ai-disposal.lua").read_text(encoding="utf-8")
CIVIC = (LUA / "ai-bridge-actions-civic.lua").read_text(encoding="utf-8")
SUPPLIES = (LUA / "ai-bridge-report-dead.lua").read_text(encoding="utf-8")   # (0.105.113) get_dead, split off ai-bridge-report-supplies
SURFACE = (LUA / "ai-builder-surface.lua").read_text(encoding="utf-8")
DUMPB = (LUA / "ai-builder-dump.lua").read_text(encoding="utf-8")

# B at 22:23 (the report as it reads now)
B_ZONE = {"id": 228, "inside": False, "items": 0, "x": 100, "y": 158, "z": 170,
          "near_items": 131, "near_unmarked": 47, "near_dumped": 46, "ramp_edge": 7}
B_DISPOSAL = {"dump_zones": [B_ZONE], "dumped_items": 0, "marked_dump": 122, "marked_dump_outside": 102,
              "marked_melt": 0, "invaders": 0, "siege": False, "smelters": 1, "magma_smelters": 0,
              "sealed_caverns": 0}


def st(zone=None, **dis):
    d = copy.deepcopy(B_DISPOSAL)
    d["dump_zones"] = [dict(B_ZONE, **(zone or {}))]
    d.update(dis)
    return {"settings": {"traits": {}, "fort_goal": "expand"}, "dwarves": {"total": 38},
            "date": {"year": 271, "tick": 17855},
            "dead": {"free_tombs": 8, "unburied": 9, "standing": {"gather_refuse": 1, "gather_refuse_outside": 1},
                     "why": {"not_ours": 2, "not_ours_loose": 0, "not_ours_beside": 2, "dump": 2}},
            "welfare": {}, "disposal": d, "projects": {"open": []}, "orders": [], "_errors": {},
            "buildings": {"workshops": {"Masons": 1}}, "stocks": {}, "supplies": {}}


def disposal(s, cfg=None):
    props, notes = [], []
    _disposal_rules(s, dict(cfg or CFG), props, notes, Memory(), player_rules(s))
    return {p.rule: p for p in props}, notes


# --- the brain -------------------------------------------------------------------------

@test("B's zone 228: ramps at its edge, 47 unmarked beside it: the dump moved to flat ground, nothing marked again")
def _():
    got, _ = disposal(st())
    p = got.get("disposal_move_dump")
    assert p and p.action == {"type": "place_dump", "inside": False, "move": True}, got.keys()
    assert "zone 228" in p.reason and "47 items" in p.reason and "flat" in p.reason, p.reason
    assert "disposal_dump_near" not in got


@test("with dump_move_ramp_edge off: said in a note, nothing asked")
def _():
    got, notes = disposal(st(), dict(CFG, dump_move_ramp_edge=False))
    assert "disposal_move_dump" not in got and "disposal_dump_near" not in got, got.keys()
    assert any("beside the garbage dump (zone 228)" in n and "ramps at its edge" in n for n in notes), notes


@test("beside a flat dump: the refuse marked again (mark_dump near, the cap from the config)")
def _():
    got, _ = disposal(st({"ramp_edge": 0, "near_unmarked": 20}))
    p = got.get("disposal_dump_near")
    assert p and p.action == {"type": "mark_dump", "near": True, "max": CFG["disposal_near_max"]}, got.keys()
    assert "disposal_move_dump" not in got


@test("below disposal_near_min, an inside dump with a ramp edge, or an older bridge (no ramp_edge): nothing asked")
def _():
    got, _ = disposal(st({"near_unmarked": CFG["disposal_near_min"] - 1}))
    assert "disposal_move_dump" not in got and "disposal_dump_near" not in got
    got, notes = disposal(st({"inside": True}))
    assert "disposal_move_dump" not in got and any("ramps at its edge" in n for n in notes)
    old = {k: v for k, v in B_ZONE.items() if not k.startswith("near") and k != "ramp_edge"}
    s = st()
    s["disposal"]["dump_zones"] = [old]
    got, _ = disposal(s)
    assert "disposal_move_dump" not in got and "disposal_dump_near" not in got
    assert "disposal_empty" not in got


@test("the destroy step counts what DF left beside a ramp-edged dump (near_dumped) and asks empty_dump near")
def _():
    got, _ = disposal(st(dumped_items=120))
    p = got.get("disposal_empty")
    assert p and p.action["near"] is True and p.action["type"] == "empty_dump", got.keys()
    assert "166 items lie in the garbage dump (46 of them beside it" in p.reason, p.reason
    # beside a flat dump they are marked again instead: not counted, no near
    got, _ = disposal(st({"ramp_edge": 0}, dumped_items=160))
    assert got["disposal_empty"].action == {"type": "empty_dump", "max": 160}, got["disposal_empty"].action
    # 120 in the zone and none beside: under the limit
    got, _ = disposal(st({"near_dumped": 0}, dumped_items=120))
    assert "disposal_empty" not in got


@test("burial_others: B's 2 bodies beside the ramp-edged dump (not_ours_beside, none loose): nothing asked")
def _():
    s = st()
    props, notes = [], []
    W._welfare_rules(s, CFG, props, notes, Memory(), {})
    assert not [p for p in props if p.rule == "burial_others"], props


@test("burial_others: B's why at 22:22 from this bridge (not_ours 2, both marked, not_ours_loose 0): nothing asked")
def _():
    s = st()
    s["dead"]["why"] = {"carried": 0, "dump": 2, "forbidden": 0, "free": 1, "in_job": 0, "in_water": 4,
                        "not_ours": 2, "outside": 4, "unreachable": 6, "not_ours_loose": 0}
    props, notes = [], []
    W._welfare_rules(s, CFG, props, notes, Memory(), {})
    assert not [p for p in props if p.rule == "burial_others"], props
    del s["dead"]["why"]["not_ours_loose"]          # as it read live (0.105.109): an older bridge, asked
    props = []
    W._welfare_rules(s, CFG, props, [], Memory(), {})
    assert [p for p in props if p.rule == "burial_others"]


@test("the new rules have hold classes and cooldowns; the config keys")
def _():
    from hold_classes import RULE_CLASS
    for r in ("disposal_dump_near", "disposal_move_dump"):
        assert r in RULE_CLASS, r
        assert isinstance(CFG[f"{r}_cooldown_ticks"], int), r
    assert CFG["disposal_near_min"] == 10 and CFG["disposal_near_max"] <= 500
    assert CFG["dump_move_ramp_edge"] is True


# --- the bridge's wiring (read from the source) ------------------------------------------

@test("the source: the report's near counts, left_beside in dump_bodies, the junk walk and the dead report")
def _():
    for snip in ("near_items = near, near_unmarked = unmarked, near_dumped = dumped,",
                 "function ramp_edge(zn)", "function left_beside(dumps, x, y, z, edges)",
                 "function near_items(zn, fn)", "function dump_near(ctx, max, res, dry_run)",
                 "if opts.near == true then dump_near(ctx, max, res, dry_run)",
                 "if opts.near == true and res.n < max then"):
        assert code_has(DISPOSAL, snip), snip
    assert DISPOSAL.count("left_beside(ctx.dumps, x, y, z, ctx.edges) then skip(res, 'beside_dump')") == 2
    assert code_has(SUPPLIES, "D.left_beside(dumps, x, y, z, edges)")
    assert code_has(SUPPLIES, "why.not_ours_beside = (why.not_ours_beside or 0) + 1")
    # B 22:22: why had no not_ours_loose (both bodies marked: the count was never set), so
    # burial_others read an older bridge and asked with not_ours (2) every cooldown
    assert code_has(SUPPLIES, "not_ours = 0, free = 0, not_ours_loose = 0}")
    assert code_has(CIVIC, "'bodies', 'junk', 'near'}")
    assert code_has(CIVIC, "B.place_dump_zone, inside, a.dry_run == true, move_from and {move_from = move_from} or nil")
    assert code_has(SURFACE, "if fits and flat and not flat_ring(x, y, z, w, h) then fits = false end")
    assert code_has(SURFACE, "empty = true, flat = true}")
    assert code_has(DUMPB, "function place_dump_zone(inside, dry_run, opts)")
    assert code_has(DUMPB, "local b = id and id ~= old.id and df.building.find(old.id)")
    assert code_has(DUMPB, "place_surface('dump', dry_run, {flat_only = old ~= nil})")
    for f in (DISPOSAL, CIVIC, SUPPLIES, SURFACE, DUMPB):
        assert len(f.encode("utf-8")) + f.count("\n") < 60 * 1024 - 1536


# --- the bridge in a fake fort (lupa) -----------------------------------------------------

PATCH = r"""
local env, W, ramps = ...
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df.building_type.Stockpile = 2
env.df.tiletype = {attrs = setmetatable({}, {__index = function(_, tt) return {shape = tt} end})}
env.df.tiletype_shape = setmetatable({}, {__index = function(_, s) return s end})
env.dfhack.maps.getTileType = function(x, y, z) return ramps[x .. ',' .. y .. ',' .. z] and 'RAMP' or 'FLOOR' end
local function inside(b, p) return p.z == b.z and p.x >= b.x1 and p.x <= b.x2 and p.y >= b.y1 and p.y <= b.y2 end
env.dfhack.buildings.findCivzonesAt = function(p)
    local out = {}
    for _, zn in ipairs(W.zones) do if inside(zn, p) then table.insert(out, zn) end end
    return out
end
env.dfhack.buildings.findAtTile = function(p)
    for _, b in ipairs(W.piles) do if inside(b, p) then return b end end
    return nil
end
"""


def fort(ramps=("9,9,149",)):
    from test_disposal_actions import world
    lua, env, w = world()
    lua.execute(PATCH, env, w, lua.table_from({r: True for r in ramps}))
    w.dump(50, 10, 10, 150)
    w.piles[1] = lua.table_from({"x1": 13, "y1": 13, "x2": 13, "y2": 13, "z": 150,
                                 "getType": lua.eval("function() return 2 end")})
    return lua, env, w


@test("lua: the report counts what lies beside zone 50 (its level and the one below, off zones and piles) and its ramp")
def _():
    need_lua()
    from test_disposal_actions import mk
    lua, env, w = fort()
    for _ in range(4):
        mk(lua, w, kind="CORPSE", race=2, flags={"forbid": True}, pos=(9, 9, 149))
    mk(lua, w, kind="ARMOR", flags={"dump": True}, pos=(9, 9, 149))
    mk(lua, w, kind="BAR", flags={"forbid": True}, pos=(12, 8, 150))       # beside, not refuse
    mk(lua, w, kind="ARMOR", flags={"forbid": True}, pos=(11, 11, 150))    # in the zone
    mk(lua, w, kind="ARMOR", flags={"forbid": True}, pos=(13, 13, 150))    # in a stockpile
    mk(lua, w, kind="ARMOR", flags={"forbid": True}, pos=(20, 20, 150))    # far
    mk(lua, w, kind="ARMOR", flags={"forbid": True}, pos=(9, 9, 148))      # two levels down
    zn = env.report().dump_zones[1]
    assert (zn["items"], zn.near_items, zn.near_unmarked, zn.near_dumped, zn.ramp_edge) == (1, 6, 5, 4, 1), \
        (zn["items"], zn.near_items, zn.near_unmarked, zn.near_dumped, zn.ramp_edge)


@test("lua: mark_dump near: refused beside a ramp's edge; beside a flat dump the refuse marked, the bar left")
def _():
    need_lua()
    from test_disposal_actions import mk, opts, skipped
    lua, env, w = fort()
    a = mk(lua, w, kind="ARMOR", flags={"forbid": True}, pos=(9, 9, 149))
    r = env.mark_dump(opts(lua, near=True), False)
    assert not r.ok and r.rejected and "zone 50" in r.error and a.flags.forbid, dict(r)
    lua, env, w = fort(ramps=())
    a = mk(lua, w, kind="ARMOR", flags={"forbid": True}, pos=(9, 9, 149))
    bar = mk(lua, w, kind="BAR", flags={"forbid": True}, pos=(9, 9, 149))
    r = env.mark_dump(opts(lua, near=True), False)
    assert r.ok and r.n == 1 and r.near == 1, dict(r)
    assert a.flags.dump and not a.flags.forbid and bar.flags.forbid and not bar.flags.dump
    assert skipped(r).get("kind") == 1, skipped(r)


@test("lua: the junk walk skips worn clothes beside a ramp-edged dump (beside_dump); beside a flat one it marks them")
def _():
    need_lua()
    from test_disposal_actions import mk, opts, skipped
    lua, env, w = fort()
    a = mk(lua, w, kind="ARMOR", wear=2, pos=(9, 9, 149))
    r = env.mark_dump(opts(lua), False)
    assert not a.flags.dump and skipped(r).get("beside_dump") == 1, (dict(r), skipped(r))
    lua, env, w = fort(ramps=())
    a = mk(lua, w, kind="ARMOR", wear=2, pos=(9, 9, 149))
    env.mark_dump(opts(lua), False)
    assert a.flags.dump


@test("lua: empty_dump near takes what DF left beside the dump (forbidden refuse), never without near")
def _():
    need_lua()
    from test_disposal_actions import mk, opts
    lua, env, w = fort()
    a = mk(lua, w, kind="ARMOR", flags={"forbid": True}, pos=(9, 9, 149))
    bar = mk(lua, w, kind="BAR", flags={"forbid": True}, pos=(9, 9, 149))
    r = env.empty_dump(opts(lua), False)
    assert not r.ok and not a.flags.removed
    r = env.empty_dump(opts(lua, near=True), False)
    assert r.ok and r.removed == 1 and a.flags.removed and not bar.flags.removed, dict(r)
    assert dict(r.by_reason) == {"near": 1}, dict(r.by_reason)


if __name__ == "__main__":
    finish()
