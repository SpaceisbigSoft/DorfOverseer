"""(0.105.51, builder 25) The dead and the unhappy (R3 live run, 15 Nov):

 1. visitors' bodies rotted in E: ai-util fort_remains kept every dwarf-race
    body as the fort's own ('kept own_dead 25', 668 indoor miasma tiles,
    dead.why.not_ours 10). corpse_side now reads the dead one's record (a
    member of the fort's group by histfig; a merchant, diplomat or visitor
    of any civ is another's); mark_dump takes those bodies (bodies, junk
    false) to a dump under the sky, and planner_welfare's burial_others asks
    for it when dead.why.not_ours > 0;
 2. C's 9 dead lay unburied 84 days before any coffin: burial_corner now at
    once with no tomb level under way, two weeks with one;
 3. recreation and stress care reach the plain unhappy when the fort's
    unhappy share passes unhappy_wide_share (E: 25-60%); a refused trinket
    hand-out moves on to the next need, then a good meal;
 4. a thirst death is journaled once (A: unit 17408 every summer y252-257).

    python tests/test_k48_dead_unhappy.py
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, skip, need_lua  # noqa: E402
from lua_modules_util import bridge_part_src  # noqa: E402  (r6) the bridge parts split
from planner import PLANNER_CONFIG, Memory  # noqa: E402
from planner_core import Proposal  # noqa: E402
import planner_welfare as W  # noqa: E402
import planner_society as PS  # noqa: E402
import planner_thirst as PT  # noqa: E402

CFG = PLANNER_CONFIG
LUA = ROOT / "lua"
UTIL = (LUA / "ai-util.lua").read_text(encoding="utf-8")
DISPOSAL = (LUA / "ai-disposal.lua").read_text(encoding="utf-8")
SYND = (LUA / "ai-syndromes.lua").read_text(encoding="utf-8")
REPORT = bridge_part_src("ai-bridge-report")
ACTS = bridge_part_src("ai-bridge-actions")
BURROWS = (LUA / "ai-society-burrows.lua").read_text(encoding="utf-8")
DAY = 1200
YEAR = 403200

# a fake game for ai-util alone: the fort's race 1, civ 7, group 70; units and
# historical figures by id; each figure's links {entity, type}
UTIL_FAKE = r"""
local util_src, units, hfs = ...
local env = setmetatable({}, {__index = _G})
local LINK = {[0] = 'MEMBER', [1] = 'FORMER_MEMBER', [6] = 'PRISONER', [8] = 'ENEMY'}
env.df = {global = {plotinfo = {race_id = 1, civ_id = 7, group_id = 70},
                    world = {items = {other = {CORPSE = {}, CORPSEPIECE = {}}}}},
          item_type = setmetatable({}, {__index = function(_, k) return k end}),
          histfig_entity_link_type = LINK,
          unit = {find = function(id) return units[id] end},
          historical_figure = {find = function(id)
              local h = hfs[id]
              if not h then return nil end
              local links = {}
              for i, l in ipairs(h) do
                  links[i] = {entity_id = l[1], getType = function() return l[2] end}
              end
              return {entity_links = links}
          end}}
env.dfhack = {persistent = {getSiteData = function(k, d) return d end},
              items = {getPosition = function(it) return it.pos.x, it.pos.y, it.pos.z end,
                       getOwner = function(it) return nil end},
              units = {isDead = function(u) return true end}}
assert(load(util_src, 'ai-util', 't', env))()
function env.item(kind, race, unit_id, hf, flags)
    local t = {kind = kind, race = race, unit_id = unit_id, hist_figure_id = hf or -1,
               pos = {x = 5, y = 5, z = 5}, flags = flags or {forbid = true, on_ground = true},
               getType = function(self) return self.kind end}
    return t
end
return env
"""


def util_env():
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)

    def lt(d):
        if isinstance(d, dict):
            return lua.table_from({k: lt(v) for k, v in d.items()})
        if isinstance(d, (list, tuple)):
            return lua.table_from([lt(v) for v in d])
        return d
    units = {
        11: {"civ_id": 7, "hist_figure_id": 111, "flags1": {}, "flags2": {}},          # a citizen
        12: {"civ_id": 9, "hist_figure_id": 112, "flags1": {}, "flags2": {"visitor": True}},   # E's visitor
        13: {"civ_id": 7, "hist_figure_id": 113, "flags1": {"merchant": True}, "flags2": {}},  # own civ's caravan
        14: {"civ_id": 9, "hist_figure_id": 114, "flags1": {}, "flags2": {}},          # joined the fort, civ kept
        15: {"civ_id": 7, "hist_figure_id": -1, "flags1": {}, "flags2": {}},           # no record to read
        16: {"civ_id": -1, "hist_figure_id": 116, "flags1": {}, "flags2": {}},         # civ -1 (no civ)
    }
    hfs = {111: [[70, 0]], 112: [[90, 0]], 113: [[7, 0]], 114: [[70, 1]], 116: [[70, 6]]}
    env = lua.execute(UTIL_FAKE, UTIL, lt(units), lt(hfs))
    return lua, env


@test("1. ai-util corpse_side: the dead one's record decides (E's visitors are another's, citizens the fort's)")
def _():
    need_lua()
    lua, env = util_env()
    ctx = env.forbid_context()
    assert ctx.group == 70, ctx.group
    side = lambda it: env.corpse_side(it, "CORPSE", ctx)   # noqa: E731
    assert side(env.item("CORPSE", 1, 11)) == "own"              # a citizen
    assert side(env.item("CORPSE", 1, 12)) == "other"            # a visitor of another civ
    assert side(env.item("CORPSE", 1, 13)) == "other"            # a merchant of the fort's civ
    assert side(env.item("CORPSE", 1, 14)) == "own"              # a former member, another civ on the unit
    assert side(env.item("CORPSE", 1, 15)) == "own"              # the fort's civ, nothing more to read
    assert side(env.item("CORPSE", 1, 16)) == "other"            # no civ, a prisoner's link only
    assert side(env.item("CORPSE", 1, 99, 111)) == "own"         # the unit gone: the body's own histfig
    assert side(env.item("CORPSE", 2, 99)) == "other"            # another race
    assert side(env.item("CORPSE", 2, 11)) == "own"              # another race, a member: the fort's


@test("1. ai-util fort_remains: a visitor's or merchant's dwarf body is no longer the fort's own; the forbidden reason is other_dead")
def _():
    need_lua()
    lua, env = util_env()
    ctx = env.forbid_context()
    visitor, merchant = env.item("CORPSE", 1, 12), env.item("CORPSEPIECE", 1, 13)
    citizen, unknown = env.item("CORPSE", 1, 11), env.item("CORPSE", 1, 15)
    assert not env.fort_remains(visitor, "CORPSE", ctx)
    assert not env.fort_remains(merchant, "CORPSEPIECE", ctx)
    assert env.fort_remains(citizen, "CORPSE", ctx) and env.fort_remains(unknown, "CORPSE", ctx)
    assert env.fort_remains(env.item("CORPSE", None, 12), "CORPSE", ctx)        # race unread: kept
    flagged = env.item("CORPSE", 1, 12, -1, lua.table_from({"forbid": True, "on_ground": True, "dead_dwarf": True}))
    assert env.fort_remains(flagged, "CORPSE", ctx)                              # DF's own BURY flag: kept
    assert tuple(env.forbidden_reason(visitor, ctx)) == ("other_dead", "other")
    assert tuple(env.forbidden_reason(citizen, ctx)) == ("own_dead", "own")


@test("1. keep_rotting and empty_dump ask ai-util fort_remains (one classifier); the report's not_ours asks corpse_side")
def _():
    assert "if U.fort_remains(it, e.kind, ctx) then return 'own_dead' end" in SYND
    assert "if U.fort_remains(it, kind, ctx) then skip(res, 'own_remains'); return end" in DISPOSAL
    assert "side_ctx.U.corpse_side(it, 'CORPSE', side_ctx) == 'own'" in REPORT
    assert "ctx.race, ctx.civ, ctx.group = fort_race_civ()" in UTIL


def disposal_world(dump_z=150):
    import test_disposal_actions as A
    lua, env, w = A.world()
    env.df["global"].plotinfo.civ_id = 7
    env.df.unit = lua.table_from({"find": lua.eval(
        "function(id) if id == 5 then return {civ_id = 7, hist_figure_id = -1, flags1 = {}, flags2 = {}} end "
        "if id == 6 then return {civ_id = 9, hist_figure_id = -1, flags1 = {}, flags2 = {visitor = true}} end "
        "return nil end")})
    w.dump(50, 10, 10, dump_z)
    return A, lua, env, w


@test("1. mark_dump bodies: E's visitor bodies indoors marked for the dump outside; the fort's, an animal's, one in the dump stay")
def _():
    need_lua()
    A, lua, env, w = disposal_world()
    visitor = A.mk(lua, w, kind="CORPSE", race=1, unit_id=6, flags={"forbid": True}, pos=(70, 70, 130))
    part = A.mk(lua, w, kind="CORPSEPIECE", race=1, unit_id=6, flags={}, pos=(71, 70, 130))
    elf = A.mk(lua, w, kind="CORPSE", race=4, unit_id=77, hist_figure_id=900, flags={}, pos=(72, 70, 130))
    citizen = A.mk(lua, w, kind="CORPSE", race=1, unit_id=5, flags={"forbid": True}, pos=(73, 70, 130))
    rat = A.mk(lua, w, kind="CORPSE", race=3, unit_id=78, hist_figure_id=-1, flags={}, pos=(74, 70, 130))
    dumped = A.mk(lua, w, kind="CORPSE", race=1, unit_id=6, flags={"forbid": True}, pos=(11, 11, 150))
    rags = A.mk(lua, w, kind="PANTS", wear=3, flags={}, pos=(75, 70, 130))
    r = env.mark_dump(A.opts(lua, bodies=True, junk=False, reasons=["free", "other_dead"], max=50), False)
    assert r.ok and r.bodies == 3, (r.ok, r.bodies, A.skipped(r), r.error)
    for it in (visitor, part, elf):
        assert it.flags.dump and not it.flags.forbid
    for it in (citizen, rat, dumped, rags):
        assert not it.flags.dump
    # with the junk too: the rags go as before
    r = env.mark_dump(A.opts(lua, bodies=True, reasons=["free", "other_dead"]), False)
    assert rags.flags.dump, A.skipped(r)


@test("1. mark_dump bodies: no dump under the sky, none marked (an indoor dump would only move the rot); without bodies, none")
def _():
    need_lua()
    A, lua, env, w = disposal_world(dump_z=120)
    visitor = A.mk(lua, w, kind="CORPSE", race=1, unit_id=6, flags={}, pos=(70, 70, 130))
    r = env.mark_dump(A.opts(lua, bodies=True, junk=False), False)
    assert not r.ok and not visitor.flags.dump and A.skipped(r).get("no_outside_dump") == 1, A.skipped(r)
    A2, lua2, env2, w2 = disposal_world()
    v2 = A2.mk(lua2, w2, kind="CORPSE", race=1, unit_id=6, flags={}, pos=(70, 70, 130))
    env2.mark_dump(A2.opts(lua2, reasons=["free", "other_dead"]), False)
    assert not v2.flags.dump


@test("1. the bridge passes mark_dump's bodies and junk through (booleans only)")
def _():
    assert "'keep_enemy_gear', 'bodies', 'junk'}) do" in ACTS


# E's own rows (states/254-autumn.json): 10 unburied, all not_ours, 3 outside; one dump outside
E_DEAD = {"free_tombs": 29, "unburied": 10, "why": {"carried": 0, "dump": 0, "forbidden": 0, "free": 0, "in_job": 0,
                                                    "not_ours": 10, "outside": 3, "unreachable": 0}}
E_DISPOSAL = {"dump_zones": [{"id": 107, "inside": False, "items": 0, "x": 100, "y": 158, "z": 170}],
              "dumped_items": 0, "invaders": 0, "siege": False, "smelters": 1}


def st(dead=None, disposal=None, **extra) -> dict:
    s = {"settings": {"traits": {}, "fort_goal": "expand"}, "dwarves": {"total": 40},
         "date": {"year": 254, "tick": 300000}, "dead": dead or {}, "welfare": {}, "disposal": disposal or {},
         "projects": {"open": []}, "orders": [], "_errors": {},
         "buildings": {"workshops": {"Masons": 1}}, "stocks": {}, "supplies": {}}
    s.update(extra)
    return s


def run_w(s, memory=None):
    props, notes = [], []
    W._welfare_rules(s, CFG, props, notes, memory, {})
    return props, notes


@test("1. burial_others: E's 10 dead of other civs: their bodies marked for the dump outside (and no coffins for them)")
def _():
    p, _ = run_w(st(copy.deepcopy(E_DEAD), copy.deepcopy(E_DISPOSAL)), Memory())
    o = [x for x in p if x.rule == "burial_others"]
    assert len(o) == 1 and o[0].action == {"type": "mark_dump", "bodies": True, "junk": False,
                                           "reasons": ["free", "other_dead"],
                                           "max": CFG["burial_others_max"]}, o
    assert "10 dead of other civs" in o[0].reason
    assert not [x for x in p if x.rule == "burial_corner"], p


@test("1. burial_others: no dump under the sky: one made outside; none with no such dead, in a siege, or a section failed")
def _():
    dis = copy.deepcopy(E_DISPOSAL)
    dis["dump_zones"][0]["inside"] = True
    p, _ = run_w(st(copy.deepcopy(E_DEAD), dis), Memory())
    o = [x for x in p if x.rule == "burial_others"]
    assert o and o[0].action == {"type": "place_surface", "kind": "dump"}, o
    s = st(copy.deepcopy(E_DEAD), dis, buildings={"clearing": {"dump": True}})
    assert not [x for x in run_w(s, Memory())[0] if x.rule == "burial_others"]
    d0 = copy.deepcopy(E_DEAD)
    d0["why"]["not_ours"] = 0
    assert not [x for x in run_w(st(d0, copy.deepcopy(E_DISPOSAL)), Memory())[0] if x.rule == "burial_others"]
    # (the bridge's not_ours_loose) all marked or in the dump already: nothing more
    dl = copy.deepcopy(E_DEAD)
    dl["why"]["not_ours_loose"] = 0
    assert not [x for x in run_w(st(dl, copy.deepcopy(E_DISPOSAL)), Memory())[0] if x.rule == "burial_others"]
    dl["why"]["not_ours_loose"] = 4
    o = [x for x in run_w(st(dl, copy.deepcopy(E_DISPOSAL)), Memory())[0] if x.rule == "burial_others"]
    assert o and "4 dead of other civs" in o[0].reason, o
    assert "why.not_ours_loose = (why.not_ours_loose or 0) + 1" in REPORT
    sg = copy.deepcopy(E_DISPOSAL)
    sg["siege"] = True
    assert not [x for x in run_w(st(copy.deepcopy(E_DEAD), sg), Memory())[0] if x.rule == "burial_others"]
    s = st(copy.deepcopy(E_DEAD), copy.deepcopy(E_DISPOSAL))
    s["_errors"] = {"disposal": "boom"}
    assert not [x for x in run_w(s, Memory())[0] if x.rule == "burial_others"]


@test("1. burial_others is a known rule (hold class, agenda theme, cooldown)")
def _():
    from planner_core import AGENDA_THEMES
    src = (ROOT / "brain" / "hold_classes.py").read_text(encoding="utf-8")
    assert '"burial_others"' in src and "burial_others" in AGENDA_THEMES
    assert CFG["burial_others_cooldown_ticks"] > 0


# --- 2. burial lag -----------------------------------------------------------------------------

@test("2. burial_corner: C's 9 dead with 0 free tombs and no tomb level under way: coffins the same cycle (was 84 days)")
def _():
    m = Memory()
    p, _ = run_w(st({"unburied": 9, "free_tombs": 0, "why": {"free": 9}}), m)
    c = [x for x in p if x.rule == "burial_corner"]
    assert c and c[0].action["max"] == min(9, CFG["burial_corner_max"]), p
    assert CFG["burial_fallback_days"] <= 14 and CFG["burial_fallback_unburied"] == 1


# --- 3. the unhappy band -----------------------------------------------------------------------

# E's spring 256: 59 citizens, 21 unhappy, 6 very unhappy (46% unhappy or worse)
E_STRESS = {"content": 11, "ecstatic": 0, "fine": 18, "happy": 3, "miserable": 0, "unhappy": 21, "very_unhappy": 6}


def soc_state(stress=None, stressed=None, total=59, **extra):
    s = {"settings": {"traits": {}}, "dwarves": {"total": total, "stress": stress or dict(E_STRESS)},
         "date": {"year": 256, "tick": 1000}, "needs": {"needs": {}, "stressed": stressed or []},
         "society": {"recreation": {"members": 0, "burrow": 1}}, "others_on_map": {},
         "buildings": {"workshops": {"Kitchen": 1, "Craftsdwarfs": 1}}, "orders": [], "_errors": {},
         "noble_rooms": {"free": {"bedroom": 0}}}
    s.update(extra)
    return s


@test("3. unhappy_share: E's spring 256 is 46% unhappy or worse; past unhappy_wide_share (0.2)")
def _():
    s = soc_state()
    assert abs(PS.unhappy_share(s) - 27 / 59) < 1e-9, PS.unhappy_share(s)
    assert PS.unhappy_wide(s, CFG)
    calm = soc_state(stress={"content": 50, "fine": 6, "unhappy": 2, "very_unhappy": 1, "miserable": 0})
    assert not PS.unhappy_wide(calm, CFG)
    assert PS.unhappy_share({"dwarves": {}}) == 0.0


@test("3. recreation: a fort past the share moves the plain unhappy in (unhappy, a fifth of the fort); a calm fort as before")
def _():
    rows = [{"id": i, "name": f"D{i}", "stress": "unhappy", "unmet": []} for i in range(3)]
    p = []
    PS._recreation_rule(soc_state(stressed=rows), CFG, rows, p, Memory())
    r = [x for x in p if x.rule == "recreation"]
    assert r and r[0].action.get("unhappy") is True and r[0].action["max"] == max(CFG["recreation_max"], 59 // 5), r
    assert "unhappy or worse" in r[0].reason
    # nobody listed, but 21 unhappy counted: still asked
    p = []
    PS._recreation_rule(soc_state(), CFG, [], p, Memory())
    assert [x for x in p if x.rule == "recreation" and x.action.get("unhappy")], p
    # a calm fort: the plain unhappy listed don't bring the burrow
    calm = soc_state(stress={"content": 50, "fine": 6, "unhappy": 2, "very_unhappy": 0, "miserable": 0}, stressed=rows)
    p = []
    PS._recreation_rule(calm, CFG, rows, p, Memory())
    assert not [x for x in p if x.rule == "recreation"], p


@test("3. the bridge: recreation takes `unhappy` (category 2 moved in); the needs report lists the unhappy, worst category first")
def _():
    assert "rec_eligible(u, unhappy and 2 or 1)" in BURROWS
    assert "cat <= (worst_cat or 1)" in BURROWS
    assert "function recreation_tick(max, days, dry_run, txt, friends, friend_days, release, unhappy)" in BURROWS
    assert "a.unhappy == true)" in ACTS
    assert "if cat <= 2 then" in REPORT
    assert "a.stress < b.stress" not in REPORT and "stress_cat[a]" in REPORT


@test("3. stress_care: past the share the plain unhappy get what they miss (a good meal); not below it")
def _():
    rows = [{"id": 7, "name": "Urist", "stress": "unhappy", "unmet": ["EatGoodMeal"], "bedroom": True}]
    p = []
    PS._stress_care(soc_state(stressed=rows), CFG, rows, p, Memory())
    sc = [x for x in p if x.rule == "stress_care"]
    assert sc and sc[0].action == {"type": "work_order", "recipe": "prepare_lavish_meal", "amount": 5}, p
    calm = soc_state(stress={"content": 50, "fine": 6, "unhappy": 2, "very_unhappy": 0, "miserable": 0}, stressed=rows)
    p = []
    PS._stress_care(calm, CFG, rows, p, Memory())
    assert not p, p
    # never out of a squad for plain unhappiness
    sq = [dict(rows[0], squad=True)]
    p = []
    PS._stress_care(soc_state(stressed=sq), CFG, sq, p, Memory())
    assert not [x for x in p if x.action.get("type") == "squad_release"], p


@test("3. stress_care: 'nobody wants something to own' refused: the next need, else a good meal (E asked 8 times)")
def _():
    from planner_core import refusal_key
    row = {"id": 9, "name": "Tosid", "stress": "miserable", "unmet": ["AcquireObject", "BeWithFriends"],
           "bedroom": True}
    s = soc_state(stressed=[row])
    s["needs"]["trinkets"] = 500
    m = Memory()
    p = []
    PS._stress_care(s, CFG, [row], p, m)
    tr = [x for x in p if x.rule == "stress_care"]
    assert tr and tr[0].action["type"] == "give_trinkets", p
    now = 256 * YEAR + 1000
    m.refusals = {refusal_key(tr[0]): {"n": 1, "at": now, "until": now + 5 * DAY, "why": "nobody wants something to own"}}
    p = []
    PS._stress_care(s, CFG, [row], p, m)
    sc = [x for x in p if x.rule == "stress_care"]
    assert sc and sc[0].action.get("recipe") == "prepare_lavish_meal", p
    # a craft need next in line comes before the meal
    row2 = dict(row, unmet=["AcquireObject", "CraftObject"])
    s2 = soc_state(stressed=[row2])
    s2["needs"].update(trinkets=500, idle_crafting={"workshops": 0})
    p = []
    PS._stress_care(s2, CFG, [row2], p, m)
    sc = [x for x in p if x.rule == "stress_care"]
    assert sc and sc[0].action == {"type": "idle_crafting"}, p


@test("3. the needs notes keep to the very unhappy or worse (the list holds the plain unhappy now)")
def _():
    rows = [{"id": 1, "name": "A", "stress": "unhappy", "unmet": []}]
    s = soc_state(stress={"content": 50, "fine": 6, "unhappy": 1}, stressed=rows)
    notes = []
    PS._needs_notes(s, CFG, notes, [], Memory())
    assert not any("very unhappy" in n for n in notes), notes


# --- 4. the thirst journal --------------------------------------------------------------------

@test("4. thirst_journal: A's unit 17408 journaled once, not again each summer (y252-257) nor on an older save's clock")
def _():
    m = Memory()
    death = {"id": 17408, "name": 'Urdim Logemoltar "Paintgilds", Glassmaker', "x": 109, "y": 151, "z": 171,
             "reason": "insane", "cancel": None, "timer": 74982}
    out = []
    for y, tick in ((253, 178760), (254, 179773), (255, 180086), (256, 181171), (257, 182161), (254, 100)):
        out += PT.thirst_journal({"date": {"year": y, "tick": tick}, "thirst": {"deaths": [death]}}, m)
    assert [e["id"] for e in out] == [17408], out


@test("4. thirst_journal: the book keeps the newest JOURNALED_KEEP ids at most")
def _():
    m = Memory()
    deaths = [{"id": i} for i in range(PT.JOURNALED_KEEP + 20)]
    PT.thirst_journal({"date": {"year": 250, "tick": 0}, "thirst": {"deaths": deaths}}, m)
    PT.thirst_journal({"date": {"year": 250, "tick": 10}, "thirst": {"deaths": []}}, m)
    assert len(m.thirst_book["journaled"]) == PT.JOURNALED_KEEP


@test("the touched Lua compiles under Lua 5.3")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime()
    chk = lua.eval('function(s, n) local f, e = load(s, n, "t"); return e end')
    for name in ("ai-util.lua", "ai-disposal.lua", "ai-bridge-report.lua", "ai-bridge-actions.lua",
                 "ai-society-burrows.lua"):
        err = chk((LUA / name).read_text(encoding="utf-8"), name)
        assert err is None, (name, err)


if __name__ == "__main__":
    finish()
