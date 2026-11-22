"""(R1 g2) Real remedies for thirst: lua/ai-thirst.lua (a patient stays a
patient once dehydrated; plan_way / open_way for no_path: the AI's own walls
and doors, else a dig; patient_help: the hospital burrow lifted and the water
carrying counted; probe for "unknown") and brain/planner_thirst.py (each
remedy counted and bounded, then Needs you; join_levels never asked again
after it joined nothing; the patients' supports).

Built from the 15-16 Nov run: F's fortify walls at x110 y148-150 z170 (the
pieces of fortify #3, 18:23:59), the four founders behind them at
x118-134 y149-153 z170 and 37 join_levels with dead_ends 0 (18:26-18:34);
B's patients Shorast (x105 y159 z165) and Tobul (x111 y159 z165), "a
patient" at 25695-32470 and "unknown" at 50249; F's 12 patients in the
hospital burrow (x111-117 y155-156 z163) with no bucket and no chief
medical dwarf; E's "unknown (drink in reach)" deaths at x107-108 y151-155.

    python tests/test_r1_g2.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import bridge_hub_src  # noqa: E402  (r8) the hub's text with its catalog and sections
import test_i2_thirst as I2  # noqa: E402  (its fake fort)

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, Proposal  # noqa: E402
import planner_thirst as PT  # noqa: E402

T, py, dwarf, drink, rows = I2.T, I2.py, I2.dwarf, I2.drink, I2.rows

# F, fortify #3 (18:23:59): the walls the gate put on the hallway floor's way in
F_WALLS = [(110, 148), (110, 149), (110, 150)]
F_DRINK = (105, 150, 170)          # the fort's side of the wall (the main stair x108 y149 is its trunk)
F_FOUNDERS = [(16787, 125, 150), (16788, 128, 150), (16783, 128, 149), (17000, 125, 149)]


def world():
    I2.need_lua()
    lua, env, w = I2.world()
    return lua, env, w


# F's z170: west of x110 the fort (walk group 1), the three AI walls at x110,
# the hallway x111-134 y148-153 (group 2), rock round it; `walls` the kind of
# the x110 tiles ('wall' the AI's, 'blocked' someone else's)
F_READER = r"""
local env, W, walls_kind = ...
env.WAY_READER = function(z)
    return function(x, y)
        if x < 60 or x > 180 or y < 100 or y > 200 then return nil end
        if x >= 100 and x <= 109 and y >= 146 and y <= 155 then return {kind = 'walk', group = 1} end
        if x == 110 and y >= 148 and y <= 150 then
            if walls_kind == 'wall' then return {kind = 'wall', cat = 'gate_pieces'} end
            return {kind = 'blocked', why = 'a wall the AI did not build'}
        end
        if x >= 111 and x <= 134 and y >= 148 and y <= 153 then return {kind = 'walk', group = 2} end
        if W.no_rock then return {kind = 'blocked', why = 'not natural rock to dig'} end
        return {kind = 'rock'}
    end
end
W.done = {remove = {}, dig = {}, unlock = {}}
env.WAY_DO = {
    remove = function(x, y, z) table.insert(W.done.remove, x .. ',' .. y .. ',' .. z) return true end,
    dig = function(x, y, z) table.insert(W.done.dig, x .. ',' .. y .. ',' .. z) return true end,
    unlock = function(b) table.insert(W.done.unlock, b.id) return true end,
}
"""


def f_fort(walls_kind="wall"):
    lua, env, w = world()
    lua.execute(F_READER, env, w, walls_kind)
    x, y, z = F_DRINK
    w.gmap[f"{x},{y},{z}"] = 1
    drink(lua, w, x, y, z, stack_size=40)
    for uid, ux, uy in F_FOUNDERS:
        w.gmap[f"{ux},{uy},170"] = 2
        dwarf(lua, w, uid, 40000, pos={"x": ux, "y": uy, "z": 170})
    return lua, env, w


# --- 1. a patient stays a patient once dehydrated (B: Shorast, Tobul) ----------------------

@test("classify: a dwarf last seen as a patient, or resting in bed, is still 'injured' once dehydrated")
def _():
    lua, env, w = world()
    c = lambda **f: env.classify(T(lua, f))
    here = dict(wells_group=1)
    assert c(timer=50249, **here) == "unknown"
    assert c(timer=50249, was_patient=True, **here) == "injured"
    assert c(timer=50249, resting=True, **here) == "injured"
    assert c(timer=50249, patient=True, **here) == "injured"


@test("report (B, Shorast at x105 y159 z165): 'a patient' at 25695, flags clear at 50249: still injured, not unknown")
def _():
    lua, env, w = world()
    w.zgroup[165] = 1
    w.well(T(lua, {"centerx": 108, "centery": 160, "z": 165}))
    u = dwarf(lua, w, 1, 25695, pos={"x": 105, "y": 159, "z": 165}, name={"full": "Shorast Lilaravuz"},
              health={"flags": {"needs_healthcare": True, "rq_diagnosis": True}})
    _, by = rows(env)
    assert by[1]["reason"] == "injured", by[1]
    u.counters2.thirst_timer = 50249
    u.health = T(lua, {"flags": {}})                 # DF's treatment flags read clear by now
    _, by = rows(env)
    assert by[1]["reason"] == "injured" and by[1]["was_patient"] is True, by[1]
    assert py(w.site["ai-overseer/thirst"])["snap"]["1"]["patient"] is True


@test("report: a dwarf resting in bed (job Rest) with water in reach is a patient")
def _():
    lua, env, w = world()
    env.df.job_type[3] = "Rest"
    w.zgroup[163] = 1
    w.well(T(lua, {"centerx": 113, "centery": 154, "z": 163}))
    dwarf(lua, w, 1, 50350, pos={"x": 117, "y": 156, "z": 163}, job={"current_job": {"job_type": 3}})
    _, by = rows(env)
    assert by[1]["reason"] == "injured" and by[1]["resting"] is True, by[1]


# --- 2. no_path: a way opened (F's founders behind the AI's own wall) --------------------------

@test("plan_way (F z170): from x125 y150 through the AI's wall at x110, no rock dug")
def _():
    lua, env, w = f_fort("wall")
    reader = env.WAY_READER(170)
    r = py(env.plan_way(reader, 125, 150, T(lua, {1: True})))
    kinds = [s["kind"] for s in r["steps"]]
    assert kinds == ["wall"], r
    assert (r["steps"][0]["x"], r["steps"][0]["y"]) in F_WALLS, r
    assert r["to"]["group"] == 1


@test("plan_way (F z170): the wall not the AI's: the shortest dig round it through rock instead")
def _():
    lua, env, w = f_fort("blocked")
    r = py(env.plan_way(env.WAY_READER(170), 125, 150, T(lua, {1: True})))
    kinds = [s["kind"] for s in r["steps"]]
    assert kinds and set(kinds) == {"rock"} and len(kinds) <= 3, r
    assert all(s["x"] in (110, 111) and s["y"] in (147, 151) for s in r["steps"]), r


@test("open_way (F): each founder's way: the AI's wall taken down, nothing dug; a dry run changes nothing")
def _():
    lua, env, w = f_fort("wall")
    r = py(env.open_way(16787, True))
    assert r["ok"] and r["dry_run"] and r["walls"] == 1 and r["rock"] == 0, r
    assert not list(w.done.remove.values())
    r = py(env.open_way(16787, False))
    assert r["ok"] and r["removed"] == 1 and r["dug"] == 0, r
    removed = list(w.done.remove.values())
    assert len(removed) == 1 and tuple(int(v) for v in removed[0].split(",")[:2]) in F_WALLS, removed
    assert not list(w.done.dig.values())
    rec = py(w.site["ai-overseer/thirst-ways"])["tiles"]
    assert rec[0]["kind"] == "wall" and rec[0]["z"] == 170


@test("open_way: a player's wall: the dig; in a siege or near a danger the AI's wall stays; no way: why")
def _():
    lua, env, w = f_fort("blocked")
    r = py(env.open_way(16787, False))
    assert r["ok"] and r["dug"] >= 1 and r["removed"] == 0, r
    lua, env, w = f_fort("wall")
    w.armed = True
    r = py(env.open_way(16787, False))
    assert r["rejected"] and "enemies" in r["error"] and not list(w.done.remove.values()), r
    w.armed = False
    w.unit(T(lua, {"id": 99, "danger": True, "citizen": False, "pos": {"x": 112, "y": 150, "z": 170}}))
    r = py(env.open_way(16787, False))
    assert r["rejected"] and "danger" in r["error"], r
    lua, env, w = f_fort("blocked")
    w.no_rock = True
    r = py(env.open_way(16787, False))
    assert r["rejected"] and "no way to drink" in r["error"] and "did not build" in r["error"], r


@test("open_way: drink already in their walk group, or none anywhere: nothing changed, said")
def _():
    lua, env, w = f_fort("wall")
    w.gmap["125,150,170"] = 1
    r = py(env.open_way(16787, False))
    assert r["ok"] and r["nothing"], r
    lua, env, w = world()
    dwarf(lua, w, 1, 40000)
    r = py(env.open_way(1, False))
    assert r["rejected"] and "no drink" in r["error"], r


# --- 3. a patient: the hospital burrow lifted, the carrying counted (F, z163) ---------------------

HB = r"""
local env, W = ...
env.dfhack.burrows.setAssignedUnit = function(b, u, on)
    W.assigned = W.assigned or {}
    table.insert(W.assigned, {b = b.id, u = u.id, on = on})
    if not on then
        for i, id in ipairs(u.burrows) do if id == b.id then table.remove(u.burrows, i) break end end
    end
end
local old = env.reqscript
env.reqscript = function(name)
    if name == 'ai-society-burrows' then return {HOSPITAL_BURROW_KEY = 'ai-overseer/hospital-burrow'} end
    return old(name)
end
"""


@test("patient_help (F: Degel in the hospital burrow at x112 y155 z163): lifted out; no carrier, bucket or well said")
def _():
    lua, env, w = world()
    lua.execute(HB, env, w)
    w.zgroup[163] = 1
    drink(lua, w, 113, 155, 163, stack_size=20)
    w.burrows[1] = T(lua, {"id": 45, "name": "AI hospital", "tiles": {"112,155,163": True}})
    w.site["ai-overseer/hospital-burrow"] = T(lua, {"burrow_id": 45, "members": {"7": 1}, "out": {}})
    dwarf(lua, w, 7, 50463, pos={"x": 112, "y": 155, "z": 163}, burrows=[45],
          health={"flags": {"needs_healthcare": True, "rq_diagnosis": True}})
    r = py(env.patient_help(7, True))
    assert r["lifted"] is True and not w.assigned, r            # a dry run: still in
    r = py(env.patient_help(7, False))
    assert r["lifted"] is True and r["carriers"] == 0 and r["buckets_free"] == 0, r
    assert set(r["missing"]) == {"carriers", "buckets", "water"}, r
    hb = py(w.site["ai-overseer/hospital-burrow"])
    assert "7" not in (hb.get("members") or {}) and "7" in hb["out"], hb
    assert py(w.assigned) == [{"b": 45, "u": 7, "on": False}]


@test("patient_help: carriers with the labour, a free bucket, a well in their group: nothing missing")
def _():
    lua, env, w = world()
    lua.execute(HB, env, w)
    env.df.unit_labor = T(lua, {"FEED_WATER_CIVILIANS": 77})
    w.zgroup[163] = 1
    w.well(T(lua, {"centerx": 113, "centery": 154, "z": 163}))
    lua.execute("local df, b = ...; df.global.world.items.other.BUCKET = b", env.df,
                T(lua, [{"flags": {}}, {"flags": {"in_job": True}}]))
    for i in range(3):
        dwarf(lua, w, 20 + i, 0, status={"labors": {77: True}})
    dwarf(lua, w, 7, 40000, pos={"x": 112, "y": 155, "z": 163},
          health={"flags": {"needs_healthcare": True, "rq_diagnosis": True}})
    r = py(env.patient_help(7, False))
    assert r["carriers"] == 3 and r["buckets"] == 2 and r["buckets_free"] == 1 and r["wells_here"] == 1, r
    assert r.get("missing") is None and r.get("lifted") is None, r


# --- 4. "unknown": looked into (E: drink in reach, beside the main stair) ----------------------

@test("probe: an AI burrow with no drink: taken out; a player's: left alone and said; nothing else seen: said")
def _():
    lua, env, w = world()
    lua.execute(HB, env, w)
    w.zgroup[168] = 1
    drink(lua, w, 110, 152, 168, stack_size=5)
    w.burrows[1] = T(lua, {"id": 7, "name": "AI recreation", "tiles": {"1,1,168": True}})
    w.burrows[2] = T(lua, {"id": 8, "name": "Masons", "tiles": {"2,2,168": True}})
    dwarf(lua, w, 1, 52000, pos={"x": 107, "y": 151, "z": 168}, burrows=[7, 8])
    r = py(env.probe(1, False))
    assert r["acted"] == 1 and r["drink_here"] == 5, r
    f = " | ".join(r["findings"])
    assert "AI recreation" in f and "taken out" in f and "Masons" in f and "left alone" in f, f
    assert py(w.assigned) == [{"b": 7, "u": 1, "on": False}]
    lua, env, w = world()
    drink(lua, w, stack_size=5)
    dwarf(lua, w, 2, 52000)
    r = py(env.probe(2, False))
    assert r["findings"] == ["nothing found in the way"] and r["acted"] == 0, r


@test("probe: the drink in reach forbidden: let go and said")
def _():
    lua, env, w = world()
    it = drink(lua, w, 11, 10, 100, flags={"forbid": True}, stack_size=2)
    dwarf(lua, w, 1, 52000)
    r = py(env.probe(1, False))
    assert r["acted"] == 1 and not it.flags.forbid and any("forbidden" in x for x in r["findings"]), r


# --- 5. the bridge's wiring ------------------------------------------------------------------------

@test("bridge: thirst_way, thirst_patient, thirst_probe wired with a dry run; words and the survival class")
def _():
    b = bridge_hub_src()
    for name, fn in (("thirst_way", "open_way"), ("thirst_patient", "patient_help"), ("thirst_probe", "probe")):
        assert re.search(name + r" = function\(a\)[\s\S]{0,500}reqscript\('ai-thirst'\)\." + fn + r"\(", b), name
    dry = b[b.index("DRY_OK = {}"):b.index("}) do DRY_OK[name] = true end")]
    assert "'thirst_way', 'thirst_patient', 'thirst_probe'" in dry
    import overseer
    import hold_classes
    for name in ("thirst_way", "thirst_patient", "thirst_probe"):
        assert name in overseer.SHORT_WORDS and name in hold_classes._SURVIVAL_ACTIONS, name
    from py_parts import py_family_src
    src = py_family_src("planner")     # (r7 d2) planner.py and its parts
    assert '_hook("note_thirst", note_thirst' in src and '"note_thirst"' in src


# --- 6. the brain: bounded, escalated ---------------------------------------------------------------

def state(rows_=None, tick=1200, **kw):
    s = {"date": {"year": 300, "tick": tick}, "thirst": {"list": rows_ or [], "deaths": []}, "orders": []}
    s.update(kw)
    return s


def row(uid, reason, timer=40000, **kw):
    return {"id": uid, "name": f"Dwarf {uid}", "reason": reason, "timer": timer, "x": 125, "y": 150, "z": 170, **kw}


def cycle(s, m, results=None, proposals=None):
    """One planning cycle and the bridge's answers to the thirst rule's actions
    (results: action type -> answer) fed back through the record hook."""
    props = list(proposals or [])
    notes: list = []
    PT._thirst_rule(s, PLANNER_CONFIG, props, notes, m)
    now = s["date"]["year"] * 403200 + s["date"]["tick"]
    for p in props:
        if p.rule == "thirst" and results and p.action.get("type") in results:
            PT.note_thirst(p, results[p.action["type"]], m, now)
    return [p for p in props if p.rule == "thirst"], notes


@test("brain (F, 12-26 Malachite y250): 4 founders no_path for 40 cycles: join_levels once, thirst_way a few, Needs you")
def _():
    m = Memory()
    retry = PLANNER_CONFIG["thirst_retry_ticks"]
    noop_join = {"action": "join_levels", "dead_ends": 0, "ok": True, "scanned": 2, "wrapped": True}
    nothing = {"ok": True, "nothing": True, "note": "a walkable way reads open already"}
    counts: dict = {}
    needs = []
    for i in range(40):
        rs = [row(uid, "no_path", timer=25767 + 1380 * i, x=x, y=y) for uid, x, y in F_FOUNDERS]
        p, n = cycle(state(rs, tick=114540 + retry * i), m, {"join_levels": noop_join, "thirst_way": nothing})
        for x in p:
            counts[x.action["type"]] = counts.get(x.action["type"], 0) + 1
        needs += [x for x in n if x.startswith("[you] ")]
    assert counts.get("join_levels") == 1, counts                 # was 37
    assert counts.get("thirst_way") == 4 * PLANNER_CONFIG["g2_thirst_way_tries"], counts
    assert needs and all("no way to drink" in x for x in needs), needs[:2]
    assert any("Dwarf 16787" in x for x in needs)


@test("brain: the first thirsty report of a no_path dwarf gets join_levels; its no-op sends the next to thirst_way")
def _():
    m = Memory()
    p, _ = cycle(state([row(1, "no_path", timer=26000)]), m,
                 {"join_levels": {"ok": True, "dead_ends": 0, "scanned": 2}})
    assert [x.action for x in p] == [{"type": "join_levels"}], p
    p, n = cycle(state([row(1, "no_path", timer=26100), row(2, "no_path", timer=26000)], tick=1300), m)
    assert [x.action["type"] for x in p] == ["thirst_way", "thirst_way"], p
    assert p[0].action == {"type": "thirst_way", "unit_id": 1, "max_dig": PLANNER_CONFIG["g2_thirst_way_dig"]}
    assert "joined nothing" in p[1].reason or "did not reach" in p[1].reason, p[1].reason


@test("brain: thirst_way refused (no way found): Needs you at once, nothing more asked")
def _():
    m = Memory()
    cycle(state([row(1, "no_path")]), m, {"join_levels": {"ok": True, "dead_ends": 0}})
    p, _ = cycle(state([row(1, "no_path")], tick=1900), m,
                 {"thirst_way": {"ok": False, "rejected": True,
                                 "error": "no way to drink found on their level within 40 tiles: a wall the AI did not build x3"}})
    assert [x.action["type"] for x in p] == ["thirst_way"]
    p, n = cycle(state([row(1, "no_path")], tick=2600), m)
    assert not p and any(x.startswith("[you] ") and "did not build" in x for x in n), n


@test("brain: a no_path dwarf who drank starts afresh (the ladder dropped)")
def _():
    m = Memory()
    cycle(state([row(1, "no_path")]), m, {"join_levels": {"ok": True, "joined": {"z": 170}}})
    assert m.thirst_book["ladder"]["1"]["n"] == {"join_levels": 1}
    cycle(state([], tick=1900), m)
    assert "1" not in m.thirst_book["ladder"]


@test("brain (F, z163): a thirsty patient: thirst_patient, then the carriers, buckets, a chief medical dwarf, a diagnoser")
def _():
    m = Memory()
    s = state([row(7, "injured", timer=40000, x=112, y=155, z=163)], supplies={"buckets": 0},
              society={"vacant": ["CHIEF_MEDICAL_DWARF", "MANAGER"]}, infection={"diagnosers": 0})
    p, n = cycle(s, m, {"thirst_patient": {"ok": True, "lifted": True, "carriers": 1, "buckets_free": 0,
                                           "missing": ["carriers", "buckets", "water"]}})
    acts = [x.action for x in p]
    assert {"type": "thirst_patient", "unit_id": 7} in acts, acts
    assert {"type": "work_order", "recipe": "wooden_bucket", "amount": 3} in acts
    assert {"type": "appoint", "office": "CHIEF_MEDICAL_DWARF"} in acts
    assert {"type": "assign_labor", "job": "DIAGNOSE", "count": 1} in acts
    s["date"]["tick"] += PLANNER_CONFIG["thirst_retry_ticks"]
    s["orders"] = [{"recipe": "wooden_bucket", "amount_left": 3}]
    p, n = cycle(s, m)
    acts = [x.action for x in p]
    assert {"type": "assign_labor", "job": "FEED_WATER_CIVILIANS", "count": 2} in acts, acts
    assert not any(a.get("recipe") == "wooden_bucket" for a in acts), acts      # ordered already


@test("brain: a patient's help tried its tries: then Needs you once dehydrated, naming what was missing")
def _():
    m = Memory()
    res = {"thirst_patient": {"ok": True, "carriers": 4, "buckets_free": 2, "missing": ["water"]}}
    tries = 0
    for i in range(8):
        s = state([row(7, "injured", timer=40000 + 2000 * i, x=112, y=155, z=163)],
                  tick=1200 + PLANNER_CONFIG["thirst_retry_ticks"] * i)
        p, n = cycle(s, m, res)
        tries += sum(1 for x in p if x.action["type"] == "thirst_patient")
    assert tries == PLANNER_CONFIG["g2_thirst_patient_tries"], tries
    assert any(x.startswith("[you] ") and "dehydrated in bed" in x and "no well or water zone" in x for x in n), n


@test("brain (E): 'unknown' gets thirst_probe from the act line (was: nothing); findings said; then Needs you")
def _():
    m = Memory()
    p, _ = cycle(state([row(1, "unknown", timer=30000)]), m)
    assert not p                                                    # below the act line: quiet
    found = {"ok": True, "acted": 0, "findings": ["a locked door not the AI's at x108 y149 z170 (left alone)"]}
    tries = 0
    for i in range(6):
        p, n = cycle(state([row(1, "unknown", timer=40000 + 3000 * i, x=107, y=151, z=168)],
                           tick=2000 + PLANNER_CONFIG["thirst_retry_ticks"] * i), m, {"thirst_probe": found})
        tries += len(p)
        if i == 1:
            assert "last time: a locked door not the AI's" in p[0].reason, p
    assert tries == PLANNER_CONFIG["g2_thirst_probe_tries"], tries
    assert any(x.startswith("[you] ") and "locked door" in x for x in n), n


@test("brain: join_levels by any rule that joined nothing holds the thirst rule's join off")
def _():
    m = Memory()
    PT.note_thirst(Proposal("join", {"type": "join_levels"}, "x", 3),
                   {"ok": True, "dead_ends": 0, "scanned": 3}, m, 300 * 403200 + 1000)
    p, _ = cycle(state([row(1, "no_path")]), m)
    assert [x.action["type"] for x in p] == ["thirst_way"], p


GAME_READER = r"""
local env, W = ...
local tiles = {}
W.tiles = tiles
-- z170: x100-109 the fort (group 1), x110 built walls, x111-120 hallway (group 2),
-- x121 rock, x122 rock beside water at x123
local function info(x, y, z)
    if x == 110 then return {shape = 'WALL', material = 'CONSTRUCTION', subterranean = false} end
    if x == 123 then return {shape = 'FLOOR', liquid = true} end
    if (x >= 100 and x <= 109) or (x >= 111 and x <= 120) then return {shape = 'FLOOR'} end
    return {shape = 'WALL', material = 'STONE', subterranean = true}
end
local B = {tile_info = info, natural_wall = function(t)
    if t.shape ~= 'WALL' or t.material ~= 'STONE' then return false end
    if t.designated then return false end
    return true
end}
local C = {ai_regions = function() return {} end,
           ai_claim = function(R, x, y, z, shape, surface) if x == 110 and y ~= 149 then return 'gate_pieces' end end}
env.dfhack.buildings = env.dfhack.buildings or {}
env.dfhack.buildings.findAtTile = function(p) return nil end
env.dfhack.constructions = {findAtTile = function(p) return p.x == 110 end}
local old = env.reqscript
env.reqscript = function(name)
    if name == 'ai-builder' then return B end
    if name == 'ai-constructions' then return C end
    return old(name)
end
for x = 100, 109 do for y = 140, 160 do W.gmap[x .. ',' .. y .. ',170'] = 1 end end
for x = 111, 120 do for y = 140, 160 do W.gmap[x .. ',' .. y .. ',170'] = 2 end end
"""


@test("game_way_reader: the AI's built wall, someone else's, a walk tile, rock, rock beside water")
def _():
    lua, env, w = world()
    lua.execute(GAME_READER, env, w)
    R = env.game_way_reader(170)
    k = lambda x, y: py(R(x, y))
    assert k(105, 150) == {"kind": "walk", "group": 1}
    assert k(110, 150) == {"kind": "wall", "cat": "gate_pieces"}
    assert k(110, 149)["kind"] == "blocked" and "did not build" in k(110, 149)["why"]
    assert k(121, 150) == {"kind": "rock"}
    assert k(122, 150)["kind"] == "blocked" and "water" in k(122, 150)["why"]
    r = py(env.plan_way(R, 115, 150, T(lua, {1: True})))
    assert [(x["kind"], x["x"]) for x in r["steps"]] == [("wall", 110)], r


if __name__ == "__main__":
    finish()
