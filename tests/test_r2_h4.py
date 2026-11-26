"""(R2 h4) Crossbows: no fort has ever had a ranged soldier.

The evidence (audit A1 row 10c and bug 3, A2 row 2 and finding 7; the 15-16
Nov run on 0.105.55, run2/<A-F>/state-last.json):
  * every crossbow squad had its bolts entry (set_uniform: "bolts": 500) and
    none handed out: `ammo = {assigned 0, wanted 500}` in A (500 bolts in
    stock), C (508), D (304), E (449); B's squad, set while 11 stacks lay
    free, got those 11 and no more. `power.ranged` (soldiers with bolts in
    the quiver) was 0 in all 14 squads; E's fire-spitting titan was never
    fought.
  * the Bowyer's workshop was asked as an ordinary `industry` workshops level
    and lost to "already N unfinished building projects" (A 5, C 8, D 4, E 4
    refusals; B never had one and met its beast with 0 armed soldiers).

Fixed:
  1. bolts: the bridge hands the free bolts to the squads' entries itself
     (lua/ai-military-gear.lua assign_bolts), reports `units` and
     `bolts_free`, and the brain asks for it (planner_army._bolts_rule);
  2. the Bowyer's workshop: asked as a lone shop with `crossbows`, which takes
     no project slot (lua/ai-builder-projects.lua start_project, one open at
     a time), for a fort with a squad and Militarism above the lowest, or one
     that met a fire breather or a flier (planner_military.crossbows_wanted);
  3. crossbows forged of metal with no bowyer's, bolts of bone at the
     craftsdwarf's;
  4. a crossbow squad's places go to those with crossbow or bow skill
     (lua/ai-military.lua pick_soldiers);
  5. the proof: a fake fort run cycle by cycle ends with 0 ranged soldiers on
     the old code and with its crossbow squad armed and carrying bolts now.

    python tests/test_r2_h4.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import bridge_hub_src  # noqa: E402  (r8) the hub's text with its catalog and sections
from lua_modules_util import module_src, bridge_part_src  # noqa: E402

from planner import Memory, PLANNER_CONFIG as CFG, plan  # noqa: E402

LUA_DIR = ROOT / "lua"
RUN2 = Path("/home/claude/run2")
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
ARMY_FAKE = re.search(r'ARMY_FAKE = r"""(.*?)"""', (ROOT / "tests" / "test_military.py").read_text(encoding="utf-8"),
                      re.S).group(1)
BUILDER_HARNESS = re.search(r'HARNESS = r"""(.*?)"""', (ROOT / "tests" / "test_builder.py").read_text(encoding="utf-8"),
                            re.S).group(1)


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


# ---- the fake fort: E's crossbow squad as the run left it ---------------------------------------------

E_SQUAD = {"id": 218, "name": "", "members": 10, "size": 10, "leader": True, "routine": "Constant training",
           "orders": 0, "ai_orders": 0, "uniform": True, "ai_uniform": "Crossbows, metal armor",
           "ammo": {"assigned": 0, "items": 0, "specs": 1, "wanted": 500},
           "power": {"armed": 9, "armored": 9, "ranged": 0, "ranged_power": 4.3}}
E_MELEE = {"id": 188, "name": "", "members": 8, "size": 10, "leader": True, "routine": "Constant training",
           "orders": 0, "ai_orders": 0, "uniform": True, "ai_uniform": "Melee, metal armor"}
TEMPLATES = ["Melee, leather armor", "Melee, metal armor", "Crossbows, leather armor", "Crossbows, metal armor"]


def fort(**gear) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["orders"] = []
    m = s["military"]
    m["uniform_templates"] = list(TEMPLATES)
    m["squads"] = [copy.deepcopy(E_MELEE), copy.deepcopy(E_SQUAD)]
    m["soldiers"] = 18
    g = {"soldiers": 18, "on_duty": 18, "armed": 17, "armored": 17, "helmed": 17, "squads": 2,
         "squads_with_uniform": 2, "ranged_armed": 9, "spare_crossbows": 0, "crossbows_total": 10, "bolts": 449,
         "ranged_places": 10, "quivers_assigned": 10, "quivers_free": 0, "spare": {}, "spare_weapons": {},
         "bars": {}, "forges": 0}
    g.update(gear)
    m["gear"] = g
    s["military"]["ranges"] = [{"id": 550, "squads": [218]}]
    s["buildings"]["zones"] = dict(s["buildings"].get("zones") or {}, ArcheryRange=1)
    return s


# ---- 1. the bolts handed out (Lua) --------------------------------------------------------------------

AMMO_FAKE = r"""
local env, eq, sq8 = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {insert = function(self, at, v)
                       local n = #self
                       if at == '#' then at = n end
                       for i = n, at + 1, -1 do self[i] = self[i - 1] end
                       self[at] = v end,
                   erase = function(self, at)
                       local n = #self
                       for i = at, n - 2 do self[i] = self[i + 1] end
                       self[n - 1] = nil end}})
end
env.vec = vec
env.df.item_type.AMMO = 38
local BOLTS, ARROWS = {id = 'ITEM_AMMO_BOLTS'}, {id = 'ITEM_AMMO_ARROWS'}
local all = {}
local function stack(id, sub, n, flags)
    local it = {id = id, subtype = sub, flags = flags or {}, n = n}
    function it:getStackSize() return self.n end
    all[id] = it
    return it
end
-- 91-94 four free stacks of 25 on DF's unassigned list; 95 forbidden; 96 arrows;
-- 97 a hunter's (his entry claims it); 98 on no list (a new stack DF never filed);
-- 99 waiting on the unmanifested list
local A = {stack(91, BOLTS, 25), stack(92, BOLTS, 25), stack(93, BOLTS, 25), stack(94, BOLTS, 25),
           stack(95, BOLTS, 25, {forbid = true}), stack(96, ARROWS, 25), stack(97, BOLTS, 25),
           stack(98, BOLTS, 20), stack(99, BOLTS, 25)}
env.df.global.world.items.other.AMMO = vec(A)
eq.items_unassigned.AMMO = vec({91, 92, 93, 94, 95, 96, 97})
eq.items_assigned.AMMO = vec({})
eq.items_unmanifested.AMMO = vec({99})
eq.hunter_ammunition = vec({{assigned = vec({97})}})
env.df.item = {find = function(id) return all[id] end}
env.df.squad_ammo_spec = {new = function() return {flags = {}, assigned = vec({}), delete = function() end} end}
env.df.global.world.raws.itemdefs.ammo = {{id = 'ITEM_AMMO_BOLTS', subtype = 0}}
env.fort_squad = function(id) return env.df.squad.find(id) end
"""


def ammo_env():
    need_lua()
    from test_military import army   # noqa: F401  (the same fake fort the 0.105.0 gear tests use)
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, eq, sq7, sq8 = lua.execute(ARMY_FAKE, module_src("ai-military.lua"))
    lua.execute(AMMO_FAKE, env, eq, sq8)
    n = lua.eval("function(v) return #v end")
    return lua, n, env, eq, sq7, sq8


@test("1 lua: assign_bolts hands the free bolts to a crossbow squad's entry (A: 500 in stock, 0 assigned)")
def _():
    lua, n, env, eq, sq7, sq8 = ammo_env()
    seq = lambda v: [v[i] for i in range(n(v))]
    # the squad's entry as set_uniform sets it: 50 a place (2 places), none handed out
    assert env.set_bolts(sq8, 100) is True
    a = env.squad_ammo(sq8)
    assert a.specs == 1 and a.wanted == 100 and a.assigned == 0 and a.units == 0, dict(a)
    assert env.assign_bolts is not None, "no assign_bolts in the bridge"
    # the free ones: 91-94 and 98 (never forbidden, arrows, a hunter's, unmanifested)
    free = env.free_bolts()
    assert sorted(free[i].it.id for i in range(1, n(free) + 1)) == [91, 92, 93, 94, 98]
    assert env.bolts_free_count() == 120
    d = env.assign_bolts(True, 20)
    assert d.ok and d.dry_run and d.would_assign == 100 and d.stacks == 4, dict(d)
    assert seq(sq8.ammo.ammunition[0].assigned) == []                         # a dry run changes nothing
    r = env.assign_bolts(False, 20)
    assert r.ok and r.bolts == 100 and r.stacks == 4, dict(r)
    assert seq(sq8.ammo.ammunition[0].assigned) == [91, 92, 93, 94]
    assert seq(eq.items_assigned.AMMO) == [91, 92, 93, 94]                     # off DF's free list, onto its assigned one
    assert seq(eq.items_unassigned.AMMO) == [95, 96, 97]
    assert eq.update.ammo and sq8.ammo.update.ammo                              # DF has them fetched
    a = env.squad_ammo(sq8)
    assert a.assigned == 4 and a.units == 100, dict(a)
    r = env.assign_bolts(False, 20)
    assert not r.ok and r.rejected and "has its bolts" in str(r.error), dict(r)
    assert env.bolts_free_count() == 20                                         # 98 left for the next squad


@test("1 lua: assign_bolts: nothing free is a refusal; the melee squad never gets any; the limit holds")
def _():
    lua, n, env, eq, sq7, sq8 = ammo_env()
    env.set_bolts(sq8, 100)
    r = env.assign_bolts(False, 2)
    assert r.ok and r.stacks == 2 and r.bolts == 50, dict(r)
    assert n(sq7.ammo.ammunition) == 0
    lua.execute("local env = ... for _, id in ipairs({91, 92, 93, 94, 98}) do env.df.item.find(id).flags.forbid = true end",
                env)
    r = env.assign_bolts(False, 20)
    assert not r.ok and r.rejected and "no free bolts" in str(r.error), dict(r)
    src = bridge_part_src("ai-bridge-actions")
    assert "function act_assign_bolts(a)" in src
    assert "assign_bolts = act_assign_bolts" in bridge_hub_src()


# ---- 1. the bolts handed out (the brain, on E's real squad) --------------------------------------------

@test("1 brain: E's crossbow squad (449 bolts, 0 assigned) is handed its bolts, not only noted")
def _():
    s = fort(bolts_free=449)
    s["military"]["squads"][1]["ammo"]["units"] = 0
    props, notes = plan(s, Memory())
    b = by_rule(props, "bolts")
    assert b and b[0].action == {"type": "assign_bolts", "limit": 20}, (b, [n for n in notes if "bolt" in n])
    assert "0 of the 500 bolts" in b[0].reason, b[0].reason
    # all handed out: nothing; none free: nothing
    s["military"]["squads"][1]["ammo"]["units"] = 500
    assert not by_rule(plan(s, Memory())[0], "bolts")
    s["military"]["squads"][1]["ammo"]["units"] = 0
    s["military"]["gear"]["bolts_free"] = 0
    assert not by_rule(plan(s, Memory())[0], "bolts")
    # an older bridge (no units, no bolts_free): the 0.105.0 note as before
    s = fort()
    props, notes = plan(s, Memory())
    assert not by_rule(props, "bolts") and any("bolts set but none handed out" in n for n in notes), notes


@test("1 brain: the run's own states: A, C, D, E each ask for their bolts once the bridge reports them")
def _():
    if not (RUN2 / "E" / "state-last.json").exists():
        print("    (run2 states not here: skipped)")
        return
    for f in "ACDE":
        s = json.loads((RUN2 / f / "state-last.json").read_text(encoding="latin-1"))
        g = s["military"]["gear"]
        g["bolts_free"] = int(g.get("bolts") or 0)                  # nothing handed out: every bolt is free
        for q in s["military"]["squads"]:
            if isinstance(q.get("ammo"), dict):
                q["ammo"]["units"] = 0
        b = by_rule(plan(s, Memory())[0], "bolts")
        assert b and b[0].action["type"] == "assign_bolts", (f, b)


# ---- 2. the Bowyer's workshop -----------------------------------------------------------------------

def bowyer_props(s, memory=None):
    return [p for p in plan(s, memory or Memory())[0] if p.action.get("type") == "start_project"
            and "Bowyers" in (p.action.get("shops") or [])]


@test("2 brain: a crossbow squad and no bowyer's: a lone Bowyer's with `crossbows` (C: refused 8 times as `industry`)")
def _():
    s = fort(crossbows_total=10, bolts=600)                     # no shortage today: still asked (bolts get used)
    p = bowyer_props(s)
    assert p and p[0].rule == "crossbow_shop", p
    a = p[0].action
    assert a["shops"] == ["Bowyers"] and a["crossbows"] is True and not a.get("added_shops"), a
    # one already being built: not asked again
    s["projects"]["open"] = [{"id": 9, "kind": "workshops", "phase": "dig", "summary": {"shops": ["Bowyers"]}}]
    assert not bowyer_props(s)
    # one built: nothing
    s = fort()
    s["buildings"]["workshops"]["Bowyers"] = 1
    assert not bowyer_props(s)


@test("2 brain: before any crossbow squad: Militarism above the lowest with a squad; -100 only after a fire breather")
def _():
    s = fort()
    s["military"]["squads"] = [copy.deepcopy(E_MELEE)]
    s["settings"]["traits"] = {"militarism": 0}
    s["others_on_map"]["threats"] = [t for t in s["others_on_map"]["threats"] if not t.get("flier")]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    p = bowyer_props(s)
    assert p and p[0].action.get("crossbows") is True, p
    s["settings"]["traits"] = {"militarism": -100}
    assert not bowyer_props(s)
    # E's titan: a fire breather on the map: the bowyer's, and remembered after it has gone
    s["others_on_map"]["threats"] = [{"id": 19900, "name": "Fishlobster", "great_danger": True, "kinds": ["Titan"],
                                      "breath": ["fire"], "hostile": True, "can_reach_dwarves": True}]
    m = Memory()
    p = bowyer_props(s, m)
    assert p and "fire breather" in p[0].reason, p
    assert m.ranged_need.get("why", "").startswith("a fire breather"), m.ranged_need
    s["others_on_map"]["threats"] = []
    p = bowyer_props(s, m)
    assert p and "met a fire breather" in p[0].reason, p
    # long ago: no more
    m.ranged_need["tick"] -= (CFG["h4_ranged_need_days"] + 1) * 1200
    assert not bowyer_props(s, m)
    # a flier counts too, with no squad at all
    s["military"]["squads"] = []
    s["others_on_map"]["threats"] = [{"id": 5, "name": "a roc", "great_danger": True, "flier": True,
                                      "can_reach_dwarves": True}]
    assert bowyer_props(s, Memory())
    # the fixture's underworld demons (fliers that can't reach anyone): nothing
    s["others_on_map"]["threats"] = [t for t in BASE["others_on_map"]["threats"] if t.get("flier")]
    assert not bowyer_props(s, Memory())


@test("2 lua: start_project: the lone `crossbows` Bowyer's takes no slot, one at a time; the bridge marks only a lone one")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(LUA_DIR)
    B, W = lua.execute(BUILDER_HARNESS, (LUA_DIR / "ai-layouts.lua").read_text(encoding="utf-8"),
                       (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8"))
    full = lua.eval("function(n) local t = {} for i = 1, n do t[i] = {id = i, kind = 'bedrooms', phase = 'dig'} end "
                    "return t end")(int(B.MAX_OPEN_PROJECTS) + int(B.URGENT_EXTRA) + 3)
    B.open_projects = lambda data: full

    def p(**kw):
        t = lua.table()
        for k, v in kw.items():
            t[k] = lua.table_from(v) if isinstance(v, list) else v
        return t
    r = B.start_project(p(kind="workshops", shops=["Bowyers"]), lua.table(), True)
    assert not r.ok and "unfinished building projects" in str(r.error), dict(r)      # the run: refused every time
    r = B.start_project(p(kind="workshops", shops=["Bowyers"], crossbows=True), lua.table(), True)
    assert "unfinished building projects" not in str(r.error), dict(r)
    # one such level open already: the next one waits for a slot like any other
    one = lua.eval("function(n) local t = {} for i = 1, n do t[i] = {id = i, kind = 'bedrooms', phase = 'dig'} end "
                   "t[n + 1] = {id = 99, kind = 'workshops', phase = 'dig', crossbows = true} return t end")(
        int(B.MAX_OPEN_PROJECTS) + int(B.URGENT_EXTRA) + 3)
    B.open_projects = lambda data: one
    r = B.start_project(p(kind="workshops", shops=["Bowyers"], crossbows=True), lua.table(), True)
    assert not r.ok and "unfinished building projects" in str(r.error), dict(r)
    # (r5 p5) the bridge's start_project run on a stand-in ai-builder (tests/bridge_behaviour.py): only a lone
    # Bowyer's level is marked
    import bridge_behaviour as BB
    lay = BB.real_module("ai-layouts")

    def marked(**a):
        got, _, _ = BB.forwarded("start_project", a, "ai-builder", "start_project", extra={"ai-layouts": lay})
        return got[0][1][0].get("crossbows")
    assert marked(kind="workshops", shops=["Bowyers"], crossbows=True) is True
    assert marked(kind="workshops", shops=["Bowyers", "Carpenters"], crossbows=True) is None
    assert marked(kind="workshops", shops=["Carpenters"], crossbows=True) is None
    assert marked(kind="workshops", shops=["Bowyers"]) is None
    # the record keeps it (the next one waits while it is open): a real level saved
    import test_builder as TB
    TB._reset(False)
    r = TB.B.start_project(TB.LUA.table_from({"kind": "workshops", "shops": TB.LUA.table_from(["Bowyers"]),
                                              "crossbows": True}), TB.LUA.table_from({"year": 255, "tick": 100}), False)
    assert r.ok, dict(r)
    saved = [q for q in TB.B.load_projects().list.values() if q.id == r.project_id]
    assert saved and saved[0].crossbows is True, dict(r)


# ---- 3. crossbows of metal, bolts of bone -------------------------------------------------------------

@test("3 brain: crossbows short and no bowyer's: forged of metal while bars are plenty (B: 63 iron and steel bars)")
def _():
    s = fort(crossbows_total=0, ranged_armed=0, bars={"STEEL": 42, "IRON": 21}, forges=1, bolts=600)
    p = [x for x in by_rule(plan(s, Memory())[0], "arms") if x.action.get("recipe") == "metal_crossbow"]
    assert p and p[0].action == {"type": "work_order", "recipe": "metal_crossbow", "amount": 5,
                                 "material": "INORGANIC:STEEL"}, p
    # no bars to spare: none (the bowyer's is asked instead)
    s = fort(crossbows_total=0, ranged_armed=0, bars={"STEEL": 10}, forges=1, bolts=600)
    assert not [x for x in by_rule(plan(s, Memory())[0], "arms") if x.action.get("recipe") == "metal_crossbow"]
    src = (LUA_DIR / "ai-bridge-orders.lua").read_text(encoding="utf-8")
    assert "metal_crossbow = {job = 'MakeWeapon', item_subtype = 'ITEM_WEAPON_CROSSBOW', kind = 'metal'}" in src
    assert "bone_bolts = {job = 'MakeAmmo', item_subtype = 'ITEM_AMMO_BOLTS', material_category = {'bone'}}" in src
    from order_check import order_needs
    assert order_needs("metal_crossbow", {"material": "INORGANIC:STEEL"})["labour"] == "FORGE_WEAPON"
    assert order_needs("bone_bolts")["shop"] == "Craftsdwarfs" and order_needs("bone_bolts")["labour"] == "BONE_CARVE"


@test("3 brain: bolts short, no forge bars and no bowyer's: bone bolts at the craftsdwarf's, the bones' reserve kept")
def _():
    s = fort(bolts=0, bars={})
    s.setdefault("needs", {})["bones"] = 40
    p = [x for x in by_rule(plan(s, Memory())[0], "arms") if x.action.get("recipe") == "bone_bolts"]
    # (item2) one order sized to the gap (500 wanted, 0 in stock: 20 lots, at most bolts_order_max)
    assert p and p[0].action == {"type": "work_order", "recipe": "bone_bolts", "amount": CFG["bolts_order_max"]}, p
    s["needs"]["bones"] = CFG["h4_bone_bolts_keep"] + 2      # (item2) the lots the reserve leaves
    p = [x for x in by_rule(plan(s, Memory())[0], "arms") if x.action.get("recipe") == "bone_bolts"]
    assert p and p[0].action["amount"] == 2, p
    s["needs"]["bones"] = CFG["h4_bone_bolts_keep"]
    assert not [x for x in by_rule(plan(s, Memory())[0], "arms") if x.action.get("recipe") == "bone_bolts"]


# ---- 4. the crossbow squad filled with shooters -------------------------------------------------------

@test("4 lua: pick_soldiers: a crossbow squad's places go to crossbow and bow skill first (the keen still first)")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute("local src = ... local env = setmetatable({}, {__index = _G}) "
                      "env.dfhack = {persistent = {getSiteData = function(k, d) return d end}} "
                      "assert(load(src, 'ai-military', 't', env))() return env", module_src("ai-military.lua"))
    cands = lua.eval("""function() return {
        {id = 1, combat = 30, best_craft = 0, rskill = 0},            -- the axe veteran
        {id = 2, combat = 5, best_craft = 3, rskill = 8},             -- a hunter, crossbow 8
        {id = 3, combat = 2, best_craft = 1, rskill = 3},
        {id = 4, combat = 0, best_craft = 0, rskill = 0, fight_focus = -20000}} end""")()
    ids = lambda out: [out[i].id for i in range(1, len(out) + 1)]
    assert ids(env.pick_soldiers(cands, 3, None, True)) == [4, 2, 3]
    assert ids(env.pick_soldiers(cands, 3)) == [4, 1, 2]                 # a melee squad: as before


# ---- 5. the proof: a fake fort, cycle by cycle -----------------------------------------------------------

def simulate(cycles=12):
    """B as it began its war (two squads, no bowyer's, every project slot
    taken, Militarism 0, wood and steel, no bolts), run cycle by cycle: each
    action the plan picks is applied as the game would (a workshops level
    without `crossbows` is refused while the slots are full; DF itself never
    hands a bolt to an entry). The squad's ranged soldiers at the end:
    armed with a crossbow and carrying bolts."""
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["orders"] = []
    m = s["military"]
    m["uniform_templates"] = list(TEMPLATES)
    m["squads"] = [dict(copy.deepcopy(E_MELEE), id=185, ai_uniform="Melee, metal armor"),
                   dict(copy.deepcopy(E_MELEE), id=205, members=10, ai_uniform="Melee, metal armor")]
    m["gear"] = {"soldiers": 18, "on_duty": 18, "armed": 18, "armored": 18, "helmed": 18, "squads": 2,
                 "squads_with_uniform": 2, "ranged_armed": 0, "spare_crossbows": 0, "crossbows_total": 0, "bolts": 0,
                 "bolts_free": 0, "spare": {}, "spare_weapons": {}, "bars": {"STEEL": 42, "IRON": 21}, "forges": 1}
    s["settings"]["traits"] = {"militarism": 0}
    s["stocks"]["wood"] = 210
    s["projects"] = {"open": [{"id": i, "kind": "bedrooms", "phase": "dig"} for i in range(3)], "max_open": 2,
                     "finished": 0}
    memory = Memory()
    for _ in range(cycles):
        props, _notes = plan(s, memory)
        g = m["gear"]
        for p in props:
            a = p.action
            t = a.get("type")
            if t == "set_uniform":
                q = next(q for q in m["squads"] if q["id"] == a["squad_id"])
                if a.get("ranged"):
                    q["ai_uniform"] = f"Crossbows, {a['kind']} armor"
                    q["ammo"] = {"specs": 1, "wanted": 50 * q["size"], "assigned": 0, "items": 0, "units": 0}
                    g["ranged_places"] = q["members"]
            elif t == "start_project" and "Bowyers" in (a.get("shops") or []) and a.get("crossbows"):
                s["buildings"]["workshops"]["Bowyers"] = 1           # no slot taken: built
            elif t == "work_order":
                r, n = a.get("recipe"), int(a.get("amount") or 0)
                if r in ("wooden_crossbow", "metal_crossbow"):
                    g["crossbows_total"] += n
                    g["ranged_armed"] = min(g["crossbows_total"], g.get("ranged_places") or 0)
                elif r in ("wooden_bolts", "metal_bolts", "bone_bolts"):
                    g["bolts"] += 25 * n
                    g["bolts_free"] += 25 * n
            elif t == "assign_bolts":
                for q in m["squads"]:
                    am = q.get("ammo")
                    if isinstance(am, dict):
                        k = min(g["bolts_free"], am["wanted"] - am["units"])
                        am["units"] += k
                        am["assigned"] += -(-k // 25)
                        g["bolts_free"] -= k
        s["date"]["tick"] = int(s["date"].get("tick") or 0) + 1200
    ranged = [q for q in m["squads"] if "crossbow" in str(q.get("ai_uniform") or "").lower()]
    g = m["gear"]
    shooters = sum(min(q["members"], g["ranged_armed"], int((q.get("ammo") or {}).get("units") or 0) // 25)
                   for q in ranged)
    return ranged, shooters, s


@test("5 proof: B's start, cycle by cycle: a crossbow squad, a bowyer's, crossbows, bolts handed out: shooters > 0")
def _():
    ranged, shooters, s = simulate()
    assert len(ranged) == 1, ranged
    q = ranged[0]
    g = s["military"]["gear"]
    assert g["crossbows_total"] >= q["members"], g
    assert q["ammo"]["units"] >= q["members"] * 25, q["ammo"]
    assert shooters == q["members"], (shooters, q, g)


if __name__ == "__main__":
    finish()
