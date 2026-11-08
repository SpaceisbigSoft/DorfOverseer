"""(0.105.26, seal fix) The gate watcher (lua/ai-gates.lua) and the cavern
seal (lua/ai-threats.lua seal_cavern) worked the same doors and hatches:

  (a) the seal locks a cavern entrance's door and shuts its lever hatch; the
      watcher, which had shut that entrance itself, opened it again once no
      danger was in sight (a hidden forgotten beast is out of sight), and the
      openings report still said `sealed`, so the brain never sealed again;
  (b) the stranded-citizens rule's open_gates (open_all) unlocked the sealed
      cavern door and pulled its hatch open;
  (c) the seal's open path pulled a hatch open (and unlocked a door) the
      watcher was holding shut against an ordinary danger at the gate.

Now: the watcher never opens what the seal holds; the seal leaves what the
watcher holds shut; `sealed` is only said of a door locked (a hatch shut)
now; the watcher pulls a held hatch that reads open shut again; the
stranded rule doesn't open a cavern entrance while a great beast is in the
caverns. Plus: the strategist's protected list, the flasks order held for a
leather mood.

    python tests/test_fix26_seal.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from lua_modules_util import module_src  # noqa: E402
from harness import test, finish  # noqa: E402

import planner  # noqa: E402
from planner import Memory, plan  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort(**kw) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["map"]["elevation_offset"] = -100
    s.update(kw)
    return s


def cave_fort(threats=None, dangers=None, **kw):
    s = fort(**kw)
    s["threats"] = threats if threats is not None else {"sealed": {}}
    s["deep"] = {"caverns": [{"name": "Cavern1", "discovered": True, "open": True, "z_top": 120, "z_bottom": 110,
                              "open_at": {"x": 5, "y": 6, "z": 121},
                              "column": [{"z": 122, "shape": "STAIR_UPDOWN"}]}],
                 "dangers": dangers if dangers is not None else
                 [{"id": 50, "name": "Ozkak", "kind": "forgotten beast", "layer": "Cavern1"}],
                 "cursed": []}
    return s


def acts(props, rule=None, typ=None):
    return [p for p in props if (rule is None or p.rule == rule) and (typ is None or p.action.get("type") == typ)]


def needs_you(notes):
    return [n for n in notes if n.startswith("[you]")]


ROW = {"id": 7, "name": "Urist", "x": 40, "y": 41, "z": 150, "cause": "lockdown", "by_ai": True,
       "out_ticks": 2400, "out_days": 2, "entrance": {"id": 1, "kind": "surface", "x": 31, "y": 140, "z": 173}}


# --- the brain ----------------------------------------------------------------------

@test("stranded: a cavern entrance isn't opened while a forgotten beast is in the caverns: Needs you instead")
def _():
    cave_row = dict(ROW, entrance={"id": 4, "kind": "cavern", "x": 9, "y": 9, "z": 110})
    s = cave_fort()
    s["entrances"]["armed"] = True
    s["entrances"]["stranded"] = [dict(cave_row)]
    props, notes = plan(s, Memory())
    assert not acts(props, typ="open_gates"), [(p.rule, p.action) for p in acts(props, typ="open_gates")]
    ny = [n for n in needs_you(notes) if "cavern entrance" in n]
    assert ny and "Ozkak" in ny[0] and "Urist" in ny[0], needs_you(notes)
    # no beast: opened as before
    s = cave_fort(dangers=[])
    s["entrances"]["armed"] = True
    s["entrances"]["stranded"] = [dict(cave_row)]
    assert acts(plan(s, Memory())[0], "stranded", "open_gates")
    # a surface entrance with the beast below: still opened (the seal's doors stay shut: open_all spares them)
    s = cave_fort()
    s["entrances"]["armed"] = True
    s["entrances"]["stranded"] = [dict(ROW)]
    assert acts(plan(s, Memory())[0], "stranded", "open_gates")


@test("steer: the protected list has no names no rule makes; the flasks, cavern doors, seal and stranded are in")
def _():
    from planner_core import STEER_PROTECTED
    for gone in ("care", "farm", "hazard", "trouble"):
        assert gone not in STEER_PROTECTED, gone
    for rule in ("flasks_order", "cavern_openings", "seal_cavern", "stranded"):
        assert rule in STEER_PROTECTED, rule
    # the names are the rules' own
    army = (ROOT / "brain" / "planner_army.py").read_text(encoding="utf-8")
    threats = (ROOT / "brain" / "planner_threats.py").read_text(encoding="utf-8")
    assert 'Proposal("flasks_order"' in army and 'Proposal("cavern_openings"' in threats
    assert 'Proposal("seal_cavern"' in threats


@test("mood: the waterskin order waits while a strange mood waits for leather, as the shoes and quivers do")
def _():
    from planner_moods import mood_blocked
    s = fort()
    s["moods"] = {"list": [{"name": "Kib", "craft": True,
                            "missing": [{"item": "SKIN_TANNED", "kind": "leather", "quantity": 1,
                                         "on_hand": False}]}]}
    recipes, _ = mood_blocked(s)
    assert "leather_quiver" in recipes, recipes        # (the harness itself)
    assert "leather_waterskin" in recipes, recipes


# --- the Lua side ------------------------------------------------------------------

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

if LuaRuntime:
    LUA = LuaRuntime(unpack_returned_tuples=True)
    t = LUA.table_from

    # the gate watcher: its reqscript answers 'ai-threats' with the threats env below
    GATES_GAME = r"""
local src = ...
local G = {citizens = {}, units = {}, groups = {}, zones = {}, mods = {}, blds = {}}
local e = setmetatable({G = G}, {__index = _G})
e.reqscript = function(n) return G.mods[n] end
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
e.COLOR_GREEN, e.COLOR_YELLOW = 2, 14
e.df = {global = {cur_year = 10, cur_year_tick = 5000,
                  world = {units = {active = G.units}, buildings = {other = {ZONE_MEETING_HALL = G.zones}}}},
        building = {find = function(id) return G.blds[id] end}}
e.dfhack = {units = {getCitizens = function() return G.citizens end,
                     getReadableName = function(u) return u.name end,
                     isAlive = function() return true end, isCitizen = function(u) return u.citizen == true end,
                     isHidden = function() return false end, isDanger = function(u) return u.danger == true end,
                     isInvader = function() return false end, isGreatDanger = function() return false end},
            maps = {getWalkableGroup = function(p) return 0 end,
                    getTileFlags = function(x, y, z) return {feature_global = false} end},
            gui = {showAnnouncement = function() end},
            timeout = function() return 1 end, timeout_active = function() return nil end}
assert(load(src, 'ai-gates', 't', e))()
return e
"""

    THREATS_GAME = r"""
local src = ...
local G = {saved = {}, citizens = {}, tiles = {}, pulled = {}, mods = {}}
local e = setmetatable({G = G}, {__index = _G})
e.reqscript = function(n) return G.mods[n] end
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
e.df = {global = {cur_year = 1, cur_year_tick = 0},
        building = {find = function(id) for _, b in pairs(G.tiles) do if b.id == id then return b end end end},
        building_type = {Door = 'Door', Hatch = 'Hatch'}}
e.dfhack = {persistent = {getSiteData = function(k, d) return G.saved[k] or d end,
                          saveSiteData = function(k, v) G.saved[k] = v end},
            units = {getReadableName = function(u) return u.name end, getCitizens = function() return G.citizens end},
            buildings = {findAtTile = function(p) return G.tiles[p.x .. ',' .. p.y .. ',' .. p.z] end},
            maps = {getTileFlags = function(x, y, z) return {feature_global = z <= 5} end},
            gui = {showAnnouncement = function() end}}
local function bld(id, ty) return {id = id, jobs = {}, door_flags = {forbidden = false, closed = false},
    getType = function() return ty end, getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end} end
G.tiles['10,10,10'] = bld(30, 'Door')        -- a cavern entrance's door
G.tiles['12,12,12'] = bld(32, 'Hatch')       -- that entrance's hatch, on its own lever 40
-- the gates module as the seal sees it (its GATES is the real watcher's: set by the test)
G.mods['ai-gates'] = {
    GATES = {entrances = {}},
    lever_links = function() return {[32] = {40}} end,
    lever_targets = function(links, l) return {32} end,
    pull_instant = function(l) table.insert(G.pulled, l); local h = G.tiles['12,12,12']
        h.door_flags.closed = not h.door_flags.closed; return true end}
assert(load(src, 'ai-threats', 't', e))()
return e
"""

    def rig(closed=True):
        """The threats module and the real gate watcher, wired as in the
        game: one cavern entrance (id 4) with door 30 and hatch 32 (lever 40)."""
        E = LUA.execute(THREATS_GAME, module_src("ai-threats.lua"))
        GE = LUA.execute(GATES_GAME, module_src("ai-gates.lua"))
        GE.G.mods["ai-threats"] = E
        door, hatch = E.G.tiles["10,10,10"], E.G.tiles["12,12,12"]
        GE.G.blds[30], GE.G.blds[32] = door, hatch
        pulls = []

        def pi(lever):
            pulls.append(lever)
            hatch.door_flags.closed = not hatch.door_flags.closed
            return True
        GE.pull_instant = pi
        ent = t({"id": 4, "kind": "cavern", "x": 9, "y": 9, "z": 10, "outs": t({}),
                 "equipment": t([t({"id": 30, "kind": "door", "x1": 10, "y1": 10, "z": 10}),
                                 t({"id": 32, "kind": "hatch", "x1": 12, "y1": 12, "z": 12,
                                    "lever_driven": True, "drive_lever": 40})])})
        GE.GATES = t({"scanned": True, "armed": True, "entrances": t([ent]),
                      "closed": t({4: True} if closed else {}), "inside": t({}), "peak": 0})
        E.G.mods["ai-gates"].GATES = GE.GATES
        return E, GE, door, hatch, pulls, ent

    def report(E):
        rep = E.openings_report(E.load_state(), 0)
        return {(rep.list[i].x, rep.list[i].y): rep.list[i] for i in range(1, rep.n + 1)}

    def danger_at_gate(GE):
        GE.distance_to = lambda e, p: 2
        GE.G.units[1] = t({"id": 9, "danger": True, "pos": t({"x": 12, "y": 12, "z": 12}), "flags1": t({})})

    @test("(a) the watcher doesn't reopen a cavern entrance the seal holds (a hidden beast is out of sight, not gone)")
    def _():
        E, GE, door, hatch, pulls, ent = rig(closed=False)
        E.survey(None)
        r = E.seal_cavern("all caverns", t([]), False, False, 1, 5, True)
        assert r.ok and door.door_flags.forbidden and hatch.door_flags.closed, dict(r)
        GE.GATES.closed = t({4: True})                     # the watcher shut it too (danger came near)
        E.G.mods["ai-gates"].GATES = GE.GATES
        for _ in range(int(GE.REOPEN_CHECKS) + 3):
            GE.check()                                     # no danger in sight
        assert door.door_flags.forbidden and hatch.door_flags.closed and not pulls, pulls
        assert GE.GATES.closed[4]
        rows = report(E)
        assert rows[(10, 10)].sealed and rows[(12, 12)].sealed
        # the beast gone: the seal leaves the watcher's entrance to it; the watcher opens it at its next look
        r = E.seal_cavern("all caverns", t([]), True, False)
        assert r.ok and r.watcher_kept == 2 and door.door_flags.forbidden and hatch.door_flags.closed, dict(r)
        GE.check()
        assert not door.door_flags.forbidden and not hatch.door_flags.closed and pulls == [40], pulls
        assert GE.GATES.closed[4] is None

    @test("(a) a sealed door or hatch something opened again reads unsealed, and the brain seals it again")
    def _():
        E, GE, door, hatch, pulls, ent = rig(closed=False)
        E.survey(None)
        E.seal_cavern("all caverns", t([]), False, False, 1, 5, True)
        door.door_flags.forbidden = False                  # (the player, or a reopen before this fix)
        hatch.door_flags.closed = False
        rows = report(E)
        assert not rows[(10, 10)].sealed and not rows[(12, 12)].sealed, (rows[(10, 10)].sealed, rows[(12, 12)].sealed)
        ops = [{k: v for k, v in dict(x).items()} for x in rows.values()]
        s = cave_fort(threats={"sealed": {"all caverns": {"doors": 1, "days": 0}}, "openings": {"list": ops, "n": len(ops)}})
        props, _ = plan(s, Memory())
        assert acts(props, "seal_cavern", "seal_cavern"), [p.action for p in props if p.rule == "seal_cavern"]
        # the seal again: the door locked, the hatch pulled shut, both sealed
        r = E.seal_cavern("all caverns", t([]), False, False, 1, 5, True)
        assert r.ok and r.locked == 2 and door.door_flags.forbidden and hatch.door_flags.closed, dict(r)
        rows = report(E)
        assert rows[(10, 10)].sealed and rows[(12, 12)].sealed

    @test("(b) open_gates (open_all) leaves the seal's door and hatch shut; the entrance waits")
    def _():
        E, GE, door, hatch, pulls, ent = rig(closed=False)
        E.survey(None)
        E.seal_cavern("all caverns", t([]), False, False, 1, 5, True)
        GE.GATES.closed = t({4: True})
        E.G.mods["ai-gates"].GATES = GE.GATES
        r = GE.open_all()
        assert door.door_flags.forbidden and hatch.door_flags.closed and not pulls, (dict(r), pulls)
        assert r.opened == 0 and r.waiting == 1 and GE.GATES.closed[4], dict(r)

    @test("(c) the seal opening leaves an entrance the watcher holds shut (an ordinary danger at the gate)")
    def _():
        E, GE, door, hatch, pulls, ent = rig(closed=False)
        E.survey(None)
        E.seal_cavern("all caverns", t([]), False, False, 1, 5, True)
        GE.GATES.closed = t({4: True})
        E.G.mods["ai-gates"].GATES = GE.GATES
        danger_at_gate(GE)
        before = len(E.G.pulled)                           # (the seal's own pull, shutting it)
        r = E.seal_cavern("all caverns", t([]), True, False)
        assert r.ok and r.watcher_kept == 2 and r.unlocked == 0, dict(r)
        assert E.G.saved["ai-overseer/threats"].sealed["all caverns"] is None
        for _ in range(8):
            GE.check()
        assert door.door_flags.forbidden and hatch.door_flags.closed and GE.GATES.closed[4]
        assert len(E.G.pulled) == before and not pulls, (list(E.G.pulled.values()), pulls)

    @test("the seal coming to a door the watcher already locked puts it on its record (not reopened by the watcher)")
    def _():
        E, GE, door, hatch, pulls, ent = rig()
        E.survey(None)
        door.door_flags.forbidden = True                   # the watcher's lockdown
        hatch.door_flags.closed = True
        r = E.seal_cavern("all caverns", t([]), False, False, 1, 5, True)
        assert r.ok and r.adopted == 2, dict(r)
        for _ in range(int(GE.REOPEN_CHECKS) + 2):
            GE.check()
        assert door.door_flags.forbidden and hatch.door_flags.closed and GE.GATES.closed[4]

    @test("the watcher pulls a lever's hatch it holds shut that reads open; a pull that fails corrects its view")
    def _():
        E, GE, door, hatch, pulls, ent = rig()
        danger_at_gate(GE)
        door.door_flags.forbidden, hatch.door_flags.closed = True, True
        GE.check()
        assert not pulls
        hatch.door_flags.closed = False                    # pulled open behind the watcher's back
        GE.check()
        assert pulls == [40] and hatch.door_flags.closed and GE.GATES.closed[4], pulls
        # a lever that won't pull: the watcher no longer thinks it shut (no danger near now)
        GE.G.units[1] = None
        GE.distance_to = lambda e, p: 999
        GE.pull_instant = lambda lever: False
        hatch.door_flags.closed = False
        GE.check()
        assert GE.GATES.closed[4] is None


if __name__ == "__main__":
    finish()
