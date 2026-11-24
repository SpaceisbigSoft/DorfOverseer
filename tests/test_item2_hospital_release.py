"""(item2) A strange mood's cloth or thread out of the hospital's stock.

B (24 Nov) and others: every thread in the fort lay in the hospital's chests
(its location's supply quota), so a mood wanting cloth or thread never had
it: the loom wove nothing, a mood takes nothing of the hospital's. Edzul died
of thirst in his mood, Udib went raving. Now, while a mood waits and the
hospital holds the fort's only cloth or thread of its kind, `hospital_release`
sets the hospital's thread (and cloth) quota to 0, remembered in the save's
site data, and sets as much as the mood lacks out of the chests; the quotas
are put back once no mood waits (after a reload too). Patients waiting for
sutures or dressings keep the stock from a fresh mood, not from an urgent one.

    python tests/test_item2_hospital_release.py
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
from lua_modules_util import module_src  # noqa: E402

import planner_moods  # noqa: E402
import planner_mood_help as MH  # noqa: E402
import hold_classes as H  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG, abs_tick, plan, TICKS_PER_DAY  # noqa: E402
from planner_core import COOLDOWN_KEYS, STEER_PROTECTED, LIMIT_EXEMPT  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"


def fort(thread_free=0, hosp_thread=15, hosp_cloth=0) -> dict:
    s = copy.deepcopy(BASE)
    s["orders"] = []
    s["buildings"]["workshops"]["Loom"] = 1
    s.setdefault("supplies", {})
    s["supplies"].update({"thread_kinds": {"plant": thread_free, "silk": 0, "yarn": 0},
                          "hospital": {"thread": hosp_thread, "cloth": hosp_cloth,
                                       "thread_kinds": {"plant": hosp_thread, "silk": 0, "yarn": 0},
                                       "cloth_kinds": {"plant": hosp_cloth, "silk": 0, "yarn": 0}}})
    s["health"] = {"patients": [], "waiting": 0, "stitch_wait": 0}
    s["mood_help"] = {"cancels": []}
    return s


def av(**kw):
    a = {"free": 0, "reach": 0, "forbidden": 0, "forbidden_reach": 0, "dump": 0, "job": 0, "other": 0,
         "held": 0, "trader": 0, "hospital": 0}
    a.update(kw)
    return a


CLOTH = {"index": 0, "item": "CLOTH", "quantity": 1, "flags": ["plant"], "avail": av()}


def mood(missing, **kw):
    m = {"unit_id": 5, "name": "Edzul", "mood": "Secretive", "craft": True, "skill": "CLOTHESMAKING",
         "workshop": "Clothiers", "items_have": 0, "items_needed": len(missing), "missing": missing, "thirst": 100}
    m.update(kw)
    return m


def fresh_memory(s, days=2) -> Memory:
    m = Memory()
    m.moods_seen = {"5": abs_tick(s) - days * TICKS_PER_DAY}
    return m


def rule(s, memory=None):
    props, notes = [], []
    planner_moods.mood_hospital_rule(s, memory if memory is not None else fresh_memory(s), CFG, props, notes)
    return props, notes


# ---- the planner -------------------------------------------------------------------------

@test("a cloth mood waits and the hospital holds the fort's only plant thread: one thread set out for the loom")
def _():
    s = fort()
    s["moods"] = {"list": [mood([copy.deepcopy(CLOTH)])]}
    props, notes = rule(s)
    assert [p.action for p in props] == [{"type": "hospital_release", "thread": 1, "kind": "plant"}], \
        [p.action for p in props]
    p = props[0]
    assert p.rule == "mood_hospital" and p.priority == 1, (p.rule, p.priority)
    assert "Edzul" in p.reason and "quota set to 0" in p.reason and "loom" in p.reason, p.reason


@test("free thread of the kind in the fort: nothing taken from the hospital")
def _():
    s = fort(thread_free=4)
    s["moods"] = {"list": [mood([copy.deepcopy(CLOTH)])]}
    props, _ = rule(s)
    assert not props, [p.action for p in props]
    # another kind's free thread is no help to a plant-cloth mood
    s = fort()
    s["supplies"]["thread_kinds"]["yarn"] = 6
    s["moods"] = {"list": [mood([copy.deepcopy(CLOTH)])]}
    assert [p.action for p in rule(s)[0]] == [{"type": "hospital_release", "thread": 1, "kind": "plant"}]


@test("the hospital holds cloth the mood can use: the cloth itself, as many as it lacks (at most what it holds)")
def _():
    s = fort(hosp_cloth=3)
    x = dict(copy.deepcopy(CLOTH), quantity=2, avail=av(hospital=3, reach=0))
    s["moods"] = {"list": [mood([x])]}
    props, _ = rule(s)
    assert [p.action for p in props] == [{"type": "hospital_release", "cloth": 2, "kind": "plant"}], \
        [p.action for p in props]
    assert "thread and cloth quota" in props[0].reason, props[0].reason
    # one within reach already: only the other
    x = dict(copy.deepcopy(CLOTH), quantity=2, avail=av(hospital=3, free=1, reach=1))
    s["moods"] = {"list": [mood([x])]}
    assert [p.action for p in rule(s)[0]] == [{"type": "hospital_release", "cloth": 1, "kind": "plant"}]


@test("a thread mood: the thread itself, of the kind it names; 'any' when it names none")
def _():
    s = fort()
    x = {"index": 0, "item": "THREAD", "quantity": 2, "flags": ["yarn"], "avail": av(hospital=3)}
    s["moods"] = {"list": [mood([x])]}
    assert [p.action for p in rule(s)[0]] == [{"type": "hospital_release", "thread": 2, "kind": "yarn"}]
    x = {"index": 0, "item": "THREAD", "quantity": 1, "flags": [], "avail": av(hospital=1)}
    s["moods"] = {"list": [mood([x])]}
    assert [p.action for p in rule(s)[0]] == [{"type": "hospital_release", "thread": 1, "kind": "any"}]
    # none of the hospital's suits it: nothing
    x = {"index": 0, "item": "THREAD", "quantity": 1, "flags": ["silk"], "avail": av()}
    s["moods"] = {"list": [mood([x])]}
    assert not rule(s)[0]


@test("no loom: no thread set out for weaving (the mood rule builds the loom first)")
def _():
    s = fort()
    s["buildings"]["workshops"].pop("Loom", None)
    s["moods"] = {"list": [mood([copy.deepcopy(CLOTH)])]}
    assert not rule(s)[0]


@test("restore: no mood waits on cloth or thread and the AI lowered the quotas: put back; else nothing")
def _():
    s = fort()
    s["moods"] = {"list": []}
    s["mood_help"]["hospital_hold"] = {"locations": 1, "at": 5, "list": [{"id": 4, "thread": 150000}]}
    props, _ = rule(s)
    assert [p.action for p in props] == [{"type": "hospital_release", "restore": True}], [p.action for p in props]
    assert props[0].rule == "mood_hospital"
    # a mood waiting on bone only: the quotas go back too
    bone = {"index": 0, "item": "NONE", "quantity": 1, "flags": ["bone"], "avail": av()}
    s["moods"] = {"list": [mood([bone])]}
    assert [p.action for p in rule(s)[0]] == [{"type": "hospital_release", "restore": True}]
    # nothing lowered: nothing to put back
    s["mood_help"].pop("hospital_hold")
    s["moods"] = {"list": []}
    assert not rule(s)[0]
    # the mood's cloth on hand now (the thread set out, woven) but not yet fetched: the hold stays
    s["mood_help"]["hospital_hold"] = {"locations": 1}
    x = dict(copy.deepcopy(CLOTH), avail=av(free=1, reach=1, enough=True))
    s["moods"] = {"list": [mood([x])]}
    assert not rule(s)[0]


@test("patients wait for dressings: a fresh mood leaves the hospital's stock (said); an urgent one still gets it")
def _():
    s = fort()
    s["health"]["stitch_wait"] = 2
    s["moods"] = {"list": [mood([copy.deepcopy(CLOTH)])]}
    props, notes = rule(s)
    assert not props, [p.action for p in props]
    assert any("2 patient(s) wait for sutures or dressings" in n and "Edzul" in n for n in notes), notes
    # thirsty: urgent
    s["moods"] = {"list": [mood([copy.deepcopy(CLOTH)], thirst=30000)]}
    props, _ = rule(s)
    assert [p.action for p in props] == [{"type": "hospital_release", "thread": 1, "kind": "plant"}]
    assert props[0].priority == 0 and "patient(s)" in props[0].reason and "thirsty" in props[0].reason, \
        props[0].reason
    # stalled 20+ days: urgent
    s["moods"] = {"list": [mood([copy.deepcopy(CLOTH)])]}
    m = fresh_memory(s, days=30)
    m.mood_progress = {"5": {"have": 0, "since": abs_tick(s) - 25 * TICKS_PER_DAY}}
    props, _ = rule(s, m)
    assert props and props[0].priority == 0 and "stalled 25 days" in props[0].reason, [p.reason for p in props]
    # the older patient list (no stitch_wait) is read too
    s["health"] = {"patients": [{"id": 1, "needs": ["dressing"]}]}
    s["moods"] = {"list": [mood([copy.deepcopy(CLOTH)])]}
    assert planner_moods.stitch_waiting(s) == 1 and not rule(s)[0]


@test("usable_thread: thread set out of the hospital after the weave's cancels counts; before them it doesn't")
def _():
    s = fort(thread_free=1)
    s["mood_help"]["cancels"] = [{"job": "Weave plant thread into cloth", "n": 4, "tick": 1000,
                                  "why": "Needs 1 unused collected plant thread"}]
    assert MH.usable_thread(s, CFG)["plant"] == 0
    s["mood_help"]["hospital_hold"] = {"locations": 1, "released": {"plant": 2000}}
    assert MH.usable_thread(s, CFG)["plant"] == 1
    s["mood_help"]["hospital_hold"]["released"] = {"plant": 500}
    assert MH.usable_thread(s, CFG)["plant"] == 0
    s["mood_help"]["hospital_hold"]["released"] = {"any": 2000}
    assert MH.usable_thread(s, CFG)["plant"] == 1
    # the cloth route then weaves it
    s["mood_help"]["hospital_hold"]["released"] = {"plant": 2000}
    acts, why = planner_moods._mood_make(s, copy.deepcopy(CLOTH), "cloth", Memory(), CFG, mood={"name": "Edzul"})
    assert any(a.get("recipe") == "weave_plant_cloth" for a, _ in acts), (acts, why)


@test("plan(): the rule is wired in (a mood_hospital proposal), and not with the moods section missing")
def _():
    s = fort()
    s["moods"] = {"list": [mood([copy.deepcopy(CLOTH)])]}
    props, _ = plan(s, fresh_memory(s))
    got = [p.action for p in props if p.rule == "mood_hospital"]
    assert got == [{"type": "hospital_release", "thread": 1, "kind": "plant"}], got
    s["_errors"] = dict(s.get("_errors") or {}, moods="boom")
    props, _ = plan(s, fresh_memory(s))
    assert not [p for p in props if p.rule == "mood_hospital"]


@test("lists: survival rule and action, steer-protected, limit-exempt, a quarter-day cooldown, a label")
def _():
    import overseer
    assert H.RULE_CLASS["mood_hospital"] == H.SURVIVAL and H.ACTION_CLASS["hospital_release"] == H.SURVIVAL
    assert "mood_hospital" in STEER_PROTECTED and "mood_hospital" in LIMIT_EXEMPT
    assert COOLDOWN_KEYS["mood_hospital"] == "mood_cooldown_ticks" and CFG["mood_cooldown_ticks"] == 300
    w = overseer.short({"type": "hospital_release", "thread": 1})
    assert w == overseer.SHORT_WORDS["hospital_release"] and "hospital" in w, w


@test("the bridge: the action, its dry run, restore while halted, the caches; the supplies by fibre; sizes")
def _():
    cat = (LUA / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
    assert "hospital_release = function(a) return reqscript('ai-mood-help').act_hospital_release(a, txt, a.dry_run == true) end," in cat
    dry = cat[cat.index("DRY_OK = {}"):cat.index("}) do DRY_OK[name] = true end")]
    assert "'hospital_release'," in dry
    assert "hospital_release = 'restore_only'" in cat[cat.index("RELEASE_WHILE_HALTED = {"):]
    sec = (LUA / "ai-bridge-sections.lua").read_text(encoding="utf-8")
    assert "CACHE_INVALIDATES.hospital_release = {'moods', 'locations'}" in sec
    sup = (LUA / "ai-bridge-report-supplies.lua").read_text(encoding="utf-8")
    assert sup.count("hosp_kind('thread_kinds', it)") == 1 and sup.count("hosp_kind('cloth_kinds', it)") == 1
    mh = (LUA / "ai-mood-help.lua").read_text(encoding="utf-8")
    assert "HOSPITAL_HOLD_KEY = 'ai-overseer/hospital-hold'" in mh and "out.hospital_hold = hh" in mh
    for f in ("ai-mood-help.lua", "ai-bridge-catalog.lua", "ai-bridge-report-supplies.lua", "ai-bridge-sections.lua"):
        assert (LUA / f).stat().st_size < 60 * 1024, f
    assert (ROOT / "brain" / "planner.py").stat().st_size < 92_000


# ---- Lua (lupa: these run on the PC) -----------------------------------------------------

WORLD = r"""
local src = ...
local W = {site = {}, cits = {{id = 3, mood = 0, job = {current_job = {}}}}}
local env = setmetatable({}, {__index = _G})
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local other = {THREAD = {}, CLOTH = {}}
W.other = other
env.df = {mood_type = {[0] = 'Fey'}, global = {cur_year = 100, cur_year_tick = 1000, world = {items = {other = other}}},
          abstract_building_type = {[7] = 'HOSPITAL', [3] = 'TEMPLE'},
          building_type = {[1] = 'Box', [2] = 'Civzone', [3] = 'Bed'}}
local function loc(id, t, thread, cloth)
    return {id = id, flags = {}, getType = function() return t end,
            c = {desired_thread = thread, desired_cloth = cloth, need_more = {thread = true, cloth = true}},
            getContents = function(self) return self.c end}
end
W.loc = loc
W.hosp = loc(4, 7, 150000, 100000)
W.temple = loc(5, 3, 5, 5)
W.locs = {W.temple, W.hosp}
W.chest = {flags = {}, bld = {id = 50}, x = 3, y = 3, z = 1}
W.bed_at = {}
local function pos_of(it)
    local up = it
    for _ = 1, 5 do
        if up.x then return up.x, up.y, up.z end
        up = up.cont
        if not up then return nil end
    end
end
env.dfhack = {
    world = {getCurrentSite = function() return {buildings = W.locs} end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end; return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
    units = {getCitizens = function() return W.cits end},
    items = {getContainer = function(it) return it.cont end,
             getHolderBuilding = function(c) return c.bld end,
             getHolderUnit = function() return nil end,
             getPosition = pos_of,
             moveToGround = function(it, p)
                 it.moved = p; it.cont = nil; it.x, it.y, it.z = p.x, p.y, p.z
                 return true
             end,
             getReadableDescription = function(it) return it.name or 'thread' end},
    maps = {getWalkableGroup = function(p) return 1 end},
    buildings = {
        findAtTile = function(p) if W.bed_at[p.x .. ',' .. p.y] then return {getType = function() return 3 end} end end,
        findCivzonesAt = function(p)
            if p.x >= 0 and p.x <= 5 and p.y >= 0 and p.y <= 5 then return {{id = 9}} end
            return {{id = 12}}
        end},
}
W.M = {AVAIL_CACHE = {stale = true},
       hospital_boxes = function() return {[50] = true}, {{id = 9}} end,
       hospital_ground = function(it) return it.on_floor == true end,
       cloth_kind = function(it) return it.fibre end}
env.reqscript = function(n)
    if n == 'ai-moods' then return W.M end
    error('reqscript ' .. n)
end
function W.item(list, id, fibre, o)
    o = o or {}
    local it = {id = id, fibre = fibre, name = o.name or (fibre .. ' ' .. list:lower()),
                flags = {in_inventory = o.on_floor == nil, forbid = o.forbid, in_job = o.in_job, owned = o.owned},
                cont = o.cont or (o.on_floor == nil and W.chest or nil), dim = o.dim,
                on_floor = o.on_floor, x = o.x, y = o.y, z = o.z}
    it.getTotalDimension = function(self) return self.dim or (list == 'THREAD' and 15000 or 10000) end
    table.insert(other[list], it)
    return it
end
function W.load()
    local e = setmetatable({}, {__index = env})
    assert(load(src, 'ai-mood-help', 't', e))()
    return e
end
W.env = W.load()
return W
"""


def world():
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    W = L.execute(WORLD, module_src("ai-mood-help.lua"))
    return L, W


def T(L, d):
    return L.table_from(d)


def in_zone(it) -> bool:
    return 0 <= it.x <= 5 and 0 <= it.y <= 5


@test("Lua: a plant thread set out of the hospital's chest, outside its zone, unforbidden; the quotas at 0, kept")
def _():
    need_lua()
    L, W = world()
    env = W.env
    silk = W.item("THREAD", 1, "silk")
    busy = W.item("THREAD", 2, "plant", T(L, {"in_job": True}))
    owned = W.item("THREAD", 3, "plant", T(L, {"owned": True}))
    short = W.item("THREAD", 4, "plant", T(L, {"dim": 4000}))
    elsewhere = W.item("THREAD", 5, "plant", T(L, {"on_floor": False, "x": 30, "y": 30, "z": 1}))
    good = W.item("THREAD", 6, "plant", T(L, {"forbid": True}))
    extra = W.item("THREAD", 7, "plant")
    # a dry run: counts, changes nothing
    r = env.act_hospital_release(T(L, {"thread": 1, "kind": "plant", "dry_run": True}))
    assert r.ok and r.thread == 1 and r.lowered == 1, dict(r)
    assert W.hosp.c.desired_thread == 150000 and good.moved is None and len(list(W.site.keys())) == 0
    r = env.act_hospital_release(T(L, {"thread": 1, "kind": "plant"}))
    assert r.ok and r.thread == 1 and r.cloth == 0 and r.lowered == 1, dict(r)
    assert good.moved is not None and not in_zone(good) and good.flags.forbid is False and good.cont is None
    for it in (silk, busy, owned, short, elsewhere, extra):
        assert it.moved is None, it.id
    # the thread quota at 0, the cloth's untouched (a thread request), the first value in the site data
    assert W.hosp.c.desired_thread == 0 and W.hosp.c.need_more.thread is False and W.hosp.c.desired_cloth == 100000
    assert W.temple.c.desired_thread == 5                       # (never lowered: not a hospital)
    rec = W.site["ai-overseer/hospital-hold"]
    assert rec.locs[1].id == 4 and rec.locs[1].thread == 150000 and rec.locs[1].cloth is None, dict(rec.locs[1])
    assert rec.released.plant > 0
    assert W.M.AVAIL_CACHE.stale is None                        # the moods' counts read again


@test("Lua: a cloth mood's cloth: the cloth quota lowered too; a second call keeps the first values")
def _():
    need_lua()
    L, W = world()
    env = W.env
    W.item("THREAD", 1, "plant")
    c1 = W.item("CLOTH", 10, "plant")
    part = W.item("CLOTH", 11, "plant", T(L, {"dim": 6000}))
    floor = W.item("CLOTH", 12, "plant", T(L, {"on_floor": True, "x": 4, "y": 4, "z": 1}))
    r = env.act_hospital_release(T(L, {"cloth": 2, "kind": "plant"}))
    assert r.ok and r.cloth == 2 and r.lowered == 2, dict(r)
    assert c1.moved is not None and floor.moved is not None and part.moved is None
    assert not in_zone(c1) and not in_zone(floor)
    assert W.hosp.c.desired_cloth == 0 and W.hosp.c.desired_thread == 0
    r = env.act_hospital_release(T(L, {"thread": 1, "kind": "plant"}))
    assert r.ok and r.lowered == 0 and r.thread == 1, dict(r)
    rec = W.site["ai-overseer/hospital-hold"]
    assert rec.locs[1].thread == 150000 and rec.locs[1].cloth == 100000 and rec.locs[2] is None
    # nothing left of the kind and the quotas at 0 already: refused, said
    r = env.act_hospital_release(T(L, {"thread": 1, "kind": "plant"}))
    assert not r.ok and r.rejected and "nothing of that kind" in r.error, dict(r)


@test("Lua: restore after a reload puts the quotas back from the site data; a player's own new value stays")
def _():
    need_lua()
    L, W = world()
    W.item("THREAD", 1, "plant")
    W.item("CLOTH", 2, "plant")
    assert W.env.act_hospital_release(T(L, {"cloth": 1, "thread": 1, "kind": "plant"})).ok
    assert W.hosp.c.desired_thread == 0 and W.hosp.c.desired_cloth == 0
    rep = W.env.report()
    assert rep.hospital_hold.locations == 1 and rep.hospital_hold.list[1].thread == 150000, dict(rep)
    W.hosp.c.desired_cloth = 30000                              # the player set it meanwhile
    env = W.load()                                              # a reload: a fresh module, the save's data
    r = env.act_hospital_release(T(L, {"restore": True}))
    assert r.ok and r.restored == 1, dict(r)
    assert W.hosp.c.desired_thread == 150000 and W.hosp.c.desired_cloth == 30000
    assert env.report().hospital_hold is None
    r = env.act_hospital_release(T(L, {"restore": True}))
    assert not r.ok and r.rejected, dict(r)
    # while halted only the putting back runs (restore_only), even with counts asked
    W.item("THREAD", 3, "plant")
    assert env.act_hospital_release(T(L, {"thread": 1, "kind": "plant"})).ok
    r = env.act_hospital_release(T(L, {"thread": 1, "kind": "plant", "restore_only": True}))
    assert r.ok and r.restored == 1 and W.hosp.c.desired_thread == 150000, dict(r)


@test("Lua: refused without a mood, without counts, with an odd kind, or without a hospital")
def _():
    need_lua()
    L, W = world()
    env = W.env
    W.item("THREAD", 1, "plant")
    assert env.act_hospital_release(T(L, {})).rejected
    assert env.act_hospital_release(T(L, {"thread": 1, "kind": "wool"})).rejected
    W.locs = T(L, {1: W.temple})
    assert "no hospital" in env.act_hospital_release(T(L, {"thread": 1})).error
    W.locs = T(L, {1: W.hosp})
    W.cits = T(L, {})
    r = env.act_hospital_release(T(L, {"thread": 1}))
    assert r.rejected and "strange mood" in r.error, dict(r)
    assert W.hosp.c.desired_thread == 150000


@test("Lua: no tile outside the hospital within reach: the item stays (said)")
def _():
    need_lua()
    L, W = world()
    env = W.env
    it = W.item("THREAD", 1, "plant")
    for x in range(-15, 21):
        for y in range(-15, 21):
            if not (0 <= x <= 5 and 0 <= y <= 5):
                W.bed_at[f"{x},{y}"] = True
    r = env.act_hospital_release(T(L, {"thread": 1, "kind": "plant"}))
    assert r.ok and r.thread == 0 and r.no_tile == 1 and r.lowered == 1, dict(r)
    assert it.moved is None


@test("Lua: the catalog forwards hospital_release to ai-mood-help with the action and txt")
def _():
    need_lua()
    import bridge_behaviour as BB
    got, out, env = BB.forwarded("hospital_release", {"thread": 1, "kind": "plant"}, "ai-mood-help",
                                 "act_hospital_release")
    assert len(got) == 1 and got[0][0] == "act_hospital_release", got
    assert env.DRY_OK.hospital_release is True and env.RELEASE_WHILE_HALTED.hospital_release == "restore_only"


finish()
