"""(0.105.47, J1) Why the moods failed (I7a: 54 failures in the 11-14 Nov
run, 49 timed out, 5 cancelled by the AI's own alarm), and the fixes:

1. ai-moods suits(): cloth and thread matched by the item's fibre (silk,
   yarn, plant), not DFHack's isSuitableItem/Material; the bridge's cloth
   counts by the same test (cloth_kind).
2. Silk: collect_webs at a Loom for a mood and the silk reserve; the webs
   stay (remove_webs, clear_webs) while silk is wanted.
3. The alarm: a gathering mood's workshop and item tiles go into the AI
   shelter (fill_shelter, refresh_shelter_due, the mood_shelter action and
   rule); the governor's far fire and other-layer cavern beasts hold.
4. _mood_make: an order DF keeps cancelling is a failed route; wool_route
   with wool grown now; thread DF won't weave counts none.
5. Notes promise a purchase only "if a caravan trade happens".
6. request_avail: each item counted for one request of a mood; rough-gem
   reserve 4.
7. A stalled request's DF flags and where the counted items lie.
8. A sand zone before collect_sand; a workshop past the cap for a mood with
   none claimed; mood_free_items not asked again for the same counts.

    python tests/test_r47_moods.py
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
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

import planner_core  # noqa: E402
import planner_moods  # noqa: E402
import planner_industry  # noqa: E402
import planner_mood_help as MH  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG, Proposal  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
FAKE = re.search(r'FAKE = r"""(.*?)"""', (ROOT / "tests" / "test_moods.py").read_text(encoding="utf-8"),
                 re.S).group(1)

# the fake game's extras: material flags on an item (it.matflags), THREAD items,
# a mood job's holder, a burrow
EXTRA = r"""
local W = ...
local env = W.env
env.df.item_type[6] = 'THREAD'; env.df.item_type.THREAD = 6
env.df.global.world.items.other.THREAD = {}
env.df.items_other_id.THREAD = 'THREAD'
local plain = env.dfhack.matinfo.decode
env.dfhack.matinfo.decode = function(a, b)
    if type(a) == 'table' then
        if a.matflags then return {material = {flags = a.matflags}} end
        return nil
    end
    return plain(a, b)
end
-- DFHack's own test refuses every cloth: only the fibre test may count it (I7a: avail {} everywhere)
env.dfhack.job.isSuitableItem = function(ji, t, st)
    if t == 1 or t == 6 then return false end
    return ji.item_type == -1 or ji.item_type == t
end
env.dfhack.job.getHolder = function(job) return job.holder end
function W.cloth(t, fibre, x, flags, stack)
    local it = W.item(t, 0, x, flags, stack)
    it.matflags = {}
    if fibre then it.matflags[fibre] = true end
    return it
end
"""


def lua_world():
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    W = L.execute(FAKE, module_src("ai-moods.lua"))
    W.reset()
    L.execute("local W = ...; W.env.df.global.world.items.other.THREAD = {}", W)
    W.env.HOSPITAL_CACHE = None
    L.execute(EXTRA, W)
    # (the fake's own item lists: THREAD made like the others)
    L.execute("""local W = ...
        local other = W.env.df.global.world.items.other
        local orig = W.item
        W.item = function(t, kind, x, flags, stack, dim)
            if t == 6 then
                local it = {id = #W.items + 1, flags = flags or {}, x = x or 1, name = 'thread'}
                it.getType = function() return 6 end
                it.getSubtype = function() return -1 end
                it.getMaterial = function() return 0 end
                it.getMaterialIndex = function() return kind end
                it.getStackSize = function() return stack or 1 end
                it.getTotalDimension = function() return dim or 15000 end
                local n = 0
                while other.THREAD[n] ~= nil do n = n + 1 end
                other.THREAD[n] = it
                table.insert(W.items, it)
                return it
            end
            return orig(t, kind, x, flags, stack, dim)
        end""", W)
    return L, W


def req(L, *rows):
    return L.table_from([L.table_from({k: (L.table_from(v) if isinstance(v, list) else v) for k, v in r.items()})
                         for r in rows])


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["orders"] = []
    s["buildings"]["workshops"].update({"Butchers": 1, "Farmers": 1, "Loom": 1})
    s["others_on_map"]["tame_animals"] = 33
    s.setdefault("supplies", {})
    return s


def cancels(*rows):
    return {"cancels": [{"job": j, "why": w, "n": n} for j, w, n in rows]}


def make(s, x, memory=None, mood=None):
    return planner_moods._mood_make(s, x, planner_core.mood_kind(x), memory or Memory(), CFG, mood=mood)


def recipes(acts):
    return [a.get("recipe") or a.get("type") for a, _ in acts]


# ---- 1. the cloth count ----------------------------------------------------------------

@test("1: a plant-cloth request counts the fort's plant cloth (and not its silk), DFHack's test refusing all cloth")
def _():
    L, W = lua_world()
    env = W.env
    j = W.job(req(L, {"t": 1, "kind": 0, "q": 20000, "flags": ["plant"]}), L.table_from([]))
    u = W.unit(7, j)
    W.cloth(1, "THREAD_PLANT", 1)
    W.cloth(1, "THREAD_PLANT", 2)
    W.cloth(1, "SILK", 3)
    W.cloth(1, "THREAD_PLANT", 200)                                  # out of walk
    a = env.mood_report(j, u)[1].avail
    assert a.free == 2 and a.reach == 2 and a.enough, dict(a)


@test("1: a silk request counts silk only; any-cloth counts every fibre; a web is no thread")
def _():
    L, W = lua_world()
    env = W.env
    j = W.job(req(L, {"t": 1, "kind": 0, "q": 30000, "flags": ["silk"]}), L.table_from([]))
    u = W.unit(7, j)
    for f in ("THREAD_PLANT", "YARN", "SILK"):
        W.cloth(1, f, 1)
    a = env.mood_report(j, u)[1].avail
    assert a.free == 1 and a.reach == 1 and not a.enough, dict(a)
    env.AVAIL_CACHE = L.table_from({})
    j2 = W.job(req(L, {"t": 1, "kind": 0, "q": 30000}), L.table_from([]))
    u2 = W.unit(8, j2)
    a = env.mood_report(j2, u2)[1].avail
    assert a.reach == 3 and a.enough, dict(a)
    # thread: a web lying where it was spun doesn't count
    j3 = W.job(req(L, {"t": 6, "kind": 0, "q": 2, "flags": ["silk"]}), L.table_from([]))
    u3 = W.unit(9, j3)
    W.cloth(6, "SILK", 1, L.table_from({"spider_web": True}))
    W.cloth(6, "SILK", 1)
    a = env.mood_report(j3, u3)[1].avail
    assert a.free == 1, dict(a)


@test("1: cloth_kind is the one fibre test the bridge's cloth and thread counts use")
def _():
    L, W = lua_world()
    env = W.env
    assert env.cloth_kind(W.cloth(1, "YARN", 1)) == "yarn"
    assert env.cloth_kind(W.cloth(1, None, 1)) is None
    src = (ROOT / "lua" / "ai-bridge-report.lua").read_text(encoding="utf-8")
    assert "MK.cloth_kind" in src and src.count("local k = kind_of(it)") == 2
    assert "out.shearable_ready" in src and "out.thread_short" in src


# ---- 6. one item, one request -------------------------------------------------------------

@test("6: one rough gem meets the first of four rough-gem requests, not all four (cached too)")
def _():
    L, W = lua_world()
    env = W.env
    rows = [{"t": 2, "kind": 5, "q": 1}] * 4
    j = W.job(req(L, *rows), L.table_from([]))
    u = W.unit(7, j)
    W.item(2, 5, 1)
    for _ in range(2):
        m = env.mood_report(j, u)
        got = [m[i].avail.reach for i in range(1, 5)]
        assert got == [1, 0, 0, 0], got
    W.item(2, 5, 2)                                                  # a second gem: the ROUGH list grew
    m = env.mood_report(j, u)
    assert [m[i].avail.reach for i in range(1, 5)] == [1, 1, 0, 0]
    assert CFG["reserve_rough_gems"] == 4


# ---- 7. where the counted items lie -------------------------------------------------------

@test("7: a request's counted items carry their spots (place, standing, in walk)")
def _():
    L, W = lua_world()
    env = W.env
    j = W.job(req(L, {"t": 3, "kind": 0, "q": 1, "flags": ["bone"]}), L.table_from([]))
    u = W.unit(7, j)
    W.item(3, 0, 4, L.table_from({"forbid": True}))
    a = env.mood_report(j, u)[1].avail
    sp = a.spots[1]
    assert sp.x == 4 and sp.standing == "forbidden" and sp.reach is True and sp.at == "ground", dict(sp)
    x = {"item": "NONE", "flags": ["bone"], "quantity": 1,
         "avail": {"free": 1, "reach": 1, "spots": [{"x": 4, "y": 1, "z": 1, "at": "in a bin", "reach": True,
                                                     "standing": "free"}]}}
    d = MH.request_detail(x)
    assert "DF's flags: bone" in d and "x4 y1 z1 in a bin" in d and "in walk" in d, d


@test("7: a stalled mood's Needs you line and journal carry the flags and the spots")
def _():
    s = fort()
    x = {"item": "NONE", "flags": ["bone"], "quantity": 1,
         "avail": {"free": 1, "reach": 1, "enough": True,
                   "spots": [{"x": 4, "y": 1, "z": 1, "at": "on a stockpile", "reach": True, "standing": "free"}]}}
    props, notes = [], []
    m = Memory()
    planner_moods._mood_materials(s, "Kubuk", "Fey", [x], 20, props, notes, CFG, memory=m, unit_id=5, stalled=20)
    line = " ".join(notes)
    assert "DF's flags: bone" in line and "on a stockpile" in line, notes
    s["moods"] = {"list": [{"unit_id": 5, "name": "Kubuk", "craft": True, "missing": [x]}]}
    m.mood_progress = {"5": {"have": 0, "since": planner_core.abs_tick(s) - 20 * 1200}}
    e = planner_moods.mood_journal(s, m)[0]
    assert e["requests"][0]["flags"] == ["bone"] and e["requests"][0]["spots"][0]["x"] == 4, e


# ---- 4. dead orders -------------------------------------------------------------------

@test("4: a yarn weave DF keeps cancelling is a failed route: the thread counts none, the next route is tried")
def _():
    s = fort()
    s["supplies"].update({"thread_kinds": {"yarn": 6, "silk": 0, "plant": 0}, "shearable": 4, "shearable_ready": 0})
    s["orders"] = [{"id": 1, "recipe": "weave_yarn_cloth", "amount_left": 1, "by_ai": True}]
    s["mood_help"] = cancels(("Weave yarn into cloth", "Needs 1 unused collected yarn thread", 40))
    assert MH.usable_thread(s)["yarn"] == 0
    x = {"item": "CLOTH", "flags": ["yarn"], "quantity": 1, "avail": {"free": 0, "reach": 0}}
    acts, why = make(s, x)
    assert not acts, acts
    assert "DF cancels the weave yarn cloth jobs" in why and "Needs 1 unused collected yarn thread" in why, why
    assert "wool grown" in why, why
    # wool grown now: shorn and spun
    s["supplies"]["shearable_ready"] = 2
    acts, why = make(s, x)
    assert recipes(acts) == ["shear_creature", "spin_thread"] and why is None, (acts, why)
    # the shearing cancelled "No creature": dead too
    s["mood_help"]["cancels"].append({"job": "Shear animal", "why": "No creature", "n": 9})
    acts, why = make(s, x)
    assert not acts and "shear creature" in why, (acts, why)


@test("4: an order cancelled by an interruption is still on its way; a queued live order is waited on")
def _():
    s = fort()
    s["supplies"].update({"thread_kinds": {"plant": 3}})
    s["orders"] = [{"id": 1, "recipe": "weave_plant_cloth", "amount_left": 1, "by_ai": True}]
    s["mood_help"] = cancels(("Weave thread into cloth", "Interrupted by a goblin", 5))
    x = {"item": "CLOTH", "flags": ["plant"], "quantity": 1, "avail": {"free": 0, "reach": 0}}
    acts, why = make(s, x)
    assert acts == [] and why is None, (acts, why)
    assert MH.dead_order(s, "weave_plant_cloth") is None


@test("4: wool_route reads the animals with wool grown now")
def _():
    s = fort()
    s["supplies"].update({"shearable": 5})
    assert planner_core.wool_route(s)
    s["supplies"]["shearable_ready"] = 0
    assert not planner_core.wool_route(s)


# ---- 2. silk -------------------------------------------------------------------------

@test("2: a silk mood with no silk thread and webs in a weaver's reach: collect webs at the Loom")
def _():
    s = fort()
    s["supplies"].update({"thread_kinds": {"silk": 0, "yarn": 0, "plant": 0}})
    s["mood_help"] = {"webs": {"total": 900, "loose": 800, "reach": 120}, "cancels": []}
    x = {"item": "CLOTH", "flags": ["silk"], "quantity": 2, "avail": {"free": 0, "reach": 0}}
    acts, why = make(s, x)
    assert recipes(acts) == ["collect_webs"] and why is None, (acts, why)
    s["mood_help"]["webs"]["reach"] = 0
    acts, why = make(s, x)
    assert not acts and "spider webs" in why and "caravan" in why, (acts, why)
    assert planner_core.RECIPE_SHOPS["collect_webs"] == "Loom"
    src = (ROOT / "lua" / "ai-bridge-orders.lua").read_text(encoding="utf-8")
    assert "ORDER_RECIPES.collect_webs = {job = 'CollectWebs'}" in src


@test("2: the silk reserve collects webs when no silk or yarn thread is at hand")
def _():
    s = fort()
    s["date"] = dict(s["date"], year=max(5, int(s["date"].get("year") or 0)))
    s["supplies"].update({"cloth_kinds": {"plant": 9, "silk": 0, "yarn": 0},
                          "thread_kinds": {"silk": 0, "yarn": 0, "plant": 0}})
    s["mood_help"] = {"webs": {"reach": 40}, "cancels": []}
    props, notes = [], []
    cfg = dict(CFG, reserve_plant_cloth=0, young_fort_days=0)
    planner_moods._mood_reserve_rule(s, Memory(), cfg, props, notes)
    rs = [p.action.get("recipe") for p in props]
    assert "collect_webs" in rs, (rs, notes)


@test("2: remove_webs waits while a mood wants silk (unless plenty lie in reach); goes on otherwise")
def _():
    s = fort()
    s["moods"] = {"list": [{"name": "Etur", "craft": True, "workshop": "Loom",
                            "missing": [{"item": "CLOTH", "flags": ["silk"], "quantity": 1,
                                         "avail": {"free": 0, "reach": 0}}]}]}
    s["mood_help"] = {"webs": {"reach": 30}}
    m = Memory()
    m.census = {"tick": planner_core.abs_tick(s), "items": {"counts": {"webs": 30000, "webs_removable": 29000}}}
    props, notes = [], []
    planner_industry._clutter_rules(s, CFG, props, notes, m)
    assert not [p for p in props if p.action.get("type") in ("remove_webs", "clear_webs")], props
    assert any("spider webs stay" in n for n in notes), notes
    s["moods"] = {"list": []}
    props, notes = [], []
    planner_industry._clutter_rules(s, CFG, props, notes, m)
    assert [p for p in props if p.action.get("type") == "remove_webs"], props


# ---- 3. the alarm ---------------------------------------------------------------------

@test("3: while the alarm is up a gathering mood's tiles outside the shelter are put in it (mood_shelter)")
def _():
    s = fort()
    s["moods"] = {"list": [{"name": "Momuz", "craft": True, "workshop": "Craftsdwarfs", "unit_id": 3}]}
    s["mood_help"] = {"shelter": {"moods": 1, "tiles": 12, "outside": 4}}
    s["civ_alert"] = True
    props, notes = [], []
    MH.mood_shelter_rule(s, Memory(), CFG, props, notes)
    assert props and props[0].action == {"type": "mood_shelter"} and "Momuz" in props[0].reason, props
    assert "mood_shelter" in planner_core.LIMIT_EXEMPT
    s["civ_alert"] = False
    props = []
    MH.mood_shelter_rule(s, Memory(), CFG, props, notes)
    assert not props
    s["civ_alert"] = True
    s["mood_help"]["shelter"]["outside"] = 0
    MH.mood_shelter_rule(s, Memory(), CFG, props, notes)
    assert not props


@test("3: the governor's part holds: fire 10 tiles off and a beast in another cavern layer raise no alarm")
def _():
    from planner_military import hazard_alert
    from planner_threats import cavern_at_risk
    s = fort()
    s["hazards"] = {"fire_near": 10}
    assert hazard_alert(s, CFG, raising=True) == ""
    caverns = [{"name": "Cavern1", "z_top": 50, "z_bottom": 45}, {"name": "Cavern2", "z_top": 30, "z_bottom": 25}]
    assert cavern_at_risk([{"z": 27}], [{"layer": "Cavern1"}], caverns) == []


@test("3: the shelter's fill, its redraw skip and the action wire in the moods' tiles")
def _():
    soc = (ROOT / "lua" / "ai-society.lua").read_text(encoding="utf-8")
    assert soc.count("reqscript('ai-mood-help').add_mood_spots(b, false)") == 2
    br = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "mood_shelter = function(a) return reqscript('ai-mood-help').act_mood_shelter(a) end" in br
    assert "'mood_shelter'," in br and "'mood_help'," in br and "'ai-mood-help'," in br


def help_world():
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    W = L.execute(r"""
        local src = ...
        local W = {burrow = {}, tiles = {}}
        local env = setmetatable({}, {__index = _G})
        env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
        local u = {id = 3, mood = 0, job = {current_job = {}}}
        env.df = {mood_type = {[0] = 'Fey'}, global = {cur_year = 100, cur_year_tick = 1000},
                  building_type = {Workshop = 1}, workshop_type = {Loom = 2}}
        env.dfhack = {
            units = {getCitizens = function() return {u} end},
            burrows = {isAssignedTile = function(b, p) return W.burrow[p.x .. ',' .. p.y .. ',' .. p.z] == true end,
                       setAssignedTile = function(b, p, on) W.burrow[p.x .. ',' .. p.y .. ',' .. p.z] = on end},
            maps = {canWalkBetween = function() return true end},
        }
        W.threats = {cancel_rows = function() return W.rows end,
                     parse_cancel = function(t) return t:match('^(.-) cancels ([^:]+): (.-)%.?%s*$') end}
        W.rows = {}
        local moods = {mood_tiles = function(unit) return W.tiles end}
        local soc = {SHELTER_NAME = 'AI shelter', find_burrow = function() return W.shelter end}
        env.reqscript = function(n)
            if n == 'ai-threats' then return W.threats end
            if n == 'ai-moods' then return moods end
            if n == 'ai-society' then return soc end
            error('reqscript ' .. n)
        end
        assert(load(src, 'ai-mood-help', 't', env))()
        W.env = env
        return W
    """, module_src("ai-mood-help.lua"))
    return L, W


@test("3: add_mood_spots puts the mood's tiles in the burrow once; the action rejects with nothing to add")
def _():
    L, W = help_world()
    env = W.env
    W.tiles = L.table_from([L.table_from({"x": 1, "y": 2, "z": 3}), L.table_from({"x": 4, "y": 5, "z": 6}),
                            L.table_from({"x": 1, "y": 2, "z": 3})])
    W.shelter = L.table_from({"id": 1})
    r = env.act_mood_shelter(L.table_from({"dry_run": True}))
    assert r.ok and r.added == 2 and len(list(W.burrow.keys())) == 0, dict(r)
    r = env.act_mood_shelter(L.table_from({}))
    assert r.ok and r.added == 2 and W.burrow["1,2,3"] is True, dict(r)
    r = env.act_mood_shelter(L.table_from({}))
    assert not r.ok and r.rejected and r.already == 2, dict(r)
    rep = env.report()
    assert rep.shelter.outside == 0 and rep.shelter.moods == 1
    W.shelter = None
    assert env.act_mood_shelter(L.table_from({})).rejected


@test("4: job_cancels tallies DF's cancels by job and reason (drink left out)")
def _():
    L, W = help_world()
    env = W.env
    W.rows = L.table_from([L.table_from({"text": t, "n": n}) for t, n in (
        ("Urist, Weaver cancels Weave yarn into cloth: Needs 1 unused collected yarn thread.", 3),
        ("Urist, Weaver cancels Weave yarn into cloth: Needs 1 unused collected yarn thread.", 2),
        ("Urist, Weaver cancels Weave yarn into cloth: Interrupted by a goblin.", 1),
        ("Kib, Miner cancels Drink: Interrupted by a goblin.", 4))])
    out = env.job_cancels(100)
    rows = [(r.job, r.why, r.n) for r in out.values()]
    assert ("Weave yarn into cloth", "Needs 1 unused collected yarn thread", 5) in rows, rows
    assert len(rows) == 2 and not any(r[0] == "Drink" for r in rows), rows


# ---- 5. the notes ---------------------------------------------------------------------

@test("5: the mood notes promise a purchase only if a caravan trade happens")
def _():
    s = fort()
    s["buildings"]["workshops"].pop("Loom", None)
    x = {"item": "CLOTH", "flags": ["silk"], "quantity": 1, "avail": {"free": 0, "reach": 0}}
    props, notes = [], []
    planner_moods._mood_materials(s, "Vutok", "Fey", [x], 4, props, notes, CFG, memory=Memory(), unit_id=5,
                                  stalled=0)
    line = " ".join(notes)
    assert "if a caravan trade happens" in line and "buys it from the next caravan" not in line, notes
    src = (ROOT / "brain" / "planner_moods.py").read_text(encoding="utf-8")
    assert "buys it from the next caravan" not in src and "bought when one comes" not in src


# ---- 8. the lows ----------------------------------------------------------------------

@test("8: raw green glass with no sand zone: the zone first (or 'no sand on this map')")
def _():
    s = fort()
    s["buildings"]["workshops"]["GlassFurnace"] = 1
    s["supplies"].update({"sand_bags": 0, "empty_bags": 4, "sand_zones": 0, "sand_layers": ["SAND_TAN"]})
    x = {"item": "ROUGH", "material": "green glass", "quantity": 1, "avail": {"free": 0, "reach": 0}}
    acts, why = make(s, x)
    assert recipes(acts) == ["sand_zone"] and why is None, (acts, why)
    s["supplies"]["sand_layers"] = []
    acts, why = make(s, x)
    assert not acts and "no sand on this map" in why, (acts, why)
    s["supplies"]["sand_zones"] = 1
    acts, why = make(s, x)
    assert recipes(acts) == ["collect_sand"], acts


@test("8: a mood with no workshop claimed for days, the kind at the cap: one more built past it, once")
def _():
    s = fort()
    s["buildings"]["workshops"]["Craftsdwarfs"] = planner_core.shops_max(
        CFG, int((s.get("dwarves") or {}).get("total") or 0))
    s["moods"] = {"list": [{"name": "Onol", "mood": "Macabre", "craft": True, "skill": "BONECARVE",
                            "unit_id": 9, "workshop": None}]}
    s["projects"] = {"open": []}
    m = Memory()
    m.moods_seen = {"9": planner_core.abs_tick(s) - 7 * 1200}
    props, notes = [], []
    planner_moods._mood_rules(s, m, CFG, props, notes)
    sp = [p for p in props if p.action.get("type") == "start_project"]
    assert sp and sp[0].action.get("mood_unit") == 9 and "past the cap" in sp[0].reason, (props, notes)
    MH.note_mood_help(sp[0], {"ok": True}, s, m, planner_core.abs_tick(s))
    props, notes = [], []
    planner_moods._mood_rules(s, m, CFG, props, notes)
    assert not [p for p in props if p.action.get("type") == "start_project"], props
    assert any("no more to build" in n for n in notes), notes


@test("8: mood_free_items isn't asked again after 'nothing forbidden' until the counts change")
def _():
    s = fort()
    x = {"item": "BAR", "quantity": 1, "avail": {"free": 0, "reach": 0, "forbidden": 2, "forbidden_reach": 1}}
    s["moods"] = {"list": [{"unit_id": 5, "craft": True, "missing": [x]}]}
    m = Memory()

    def frees():
        props, notes = [], []
        planner_moods._mood_materials(s, "Asen", "Fey", [x], 4, props, notes, CFG, memory=m, unit_id=5, stalled=0)
        return [p for p in props if p.action.get("type") == "mood_free_items"]
    p = frees()
    assert p
    MH.note_mood_help(p[0], {"ok": False, "rejected": True,
                             "error": "nothing forbidden or dumped within the dwarf's walk that the mood can use"},
                      s, m, planner_core.abs_tick(s))
    assert not frees()
    x["avail"]["forbidden_reach"] = 2                                 # the counts changed: asked again
    assert frees()


@test("watch-in-game has the 0.105.47 J1 block")
def _():
    w = (ROOT / "docs" / "watch-in-game.md").read_text(encoding="utf-8")
    assert "0.105.47" in w and "mood_shelter" in w and "collect_webs" in w


if __name__ == "__main__":
    sys.exit(finish())
