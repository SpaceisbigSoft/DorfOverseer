"""(item1) A patient up and walking is not 'injured'; why no water comes to a
patient in bed; get_up (lua/ai-thirst.lua classify / report, the remedies
part's patient_help, the bridge's thirst_patient).

Built from fort B, 24 Nov 20:05-20:11: Zutthan (unit 18458), infected
wounds, "needs immobilize, dressing, surgery", 126 days waiting, never
diagnosed, up and at his crafts (MakeCrafts; a tantrum a minute before he
died), called 'injured' so the brain waited for water DF never carries to a
dwarf who is up; Uvash (17126) in a bed of hospital zone #1342 (z160), 2
hospital buckets, 5 wells in his walk group, 20 carriers, no GiveWater job,
dead at thirst ~74500.

    python tests/test_item1_thirst_patient.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import bridge_hub_src  # noqa: E402
import test_i2_thirst as I2  # noqa: E402  (its fake fort)

T, py, dwarf, rows = I2.T, I2.py, I2.dwarf, I2.rows

REST, CRAFTS, GIVE_WATER = 3, 4, 9
CARE = {"needs_healthcare": True, "rq_immobilize": True, "rq_dressing": True, "rq_surgery": True}
LEGS = {"limbs_stand_max": 2, "limbs_stand_count": 2}
UVASH_AT = {"x": 120, "y": 140, "z": 160}


def world():
    I2.need_lua()
    lua, env, w = I2.world()
    env.df.job_type[REST] = "Rest"
    env.df.job_type[CRAFTS] = "MakeCrafts"
    env.df.job_type[GIVE_WATER] = "GiveWater"
    return lua, env, w


# B's hospital: zone #1342 at x118-124 y138-142 z160 (location 12, 2 buckets
# of 2 wanted), a bed at Uvash's tile; DF's job list (GiveWater jobs given as
# {patient id or false, worker id}); dfhack.job.removeJob ends a unit's job
HOSP = r"""
local env, W, give = ...
local df = env.df
df.building_type = {[2] = 'Bed', [3] = 'Table'}
df.abstract_building_type = {[5] = 'HOSPITAL', [6] = 'TAVERN'}
df.general_ref_type = {[1] = 'UNIT_WORKER', [2] = 'UNIT_PATIENT'}
W.beds = W.beds or {['120,140,160'] = true}
W.removed = {}
local zone = {id = 1342, location_id = 12, x1 = 118, y1 = 138, x2 = 124, y2 = 142, z = 160}
local hosp = {id = 12, getType = function() return 5 end,
              getContents = function() return {count_buckets = 2, desired_buckets = 2, building_ids = {1342}} end}
local tavern = {id = 13, getType = function() return 6 end}
env.dfhack.buildings = {
    findAtTile = function(p)
        if W.beds[p.x .. ',' .. p.y .. ',' .. p.z] then return {getType = function() return 2 end} end
        return nil
    end,
    findCivzonesAt = function(p)
        if p.z == zone.z and p.x >= zone.x1 and p.x <= zone.x2 and p.y >= zone.y1 and p.y <= zone.y2 then
            return {zone}
        end
        return {}
    end,
}
env.dfhack.world = {getCurrentSite = function() return {buildings = {tavern, hosp}} end}
local head = {}
local last = head
for _, g in ipairs(give or {}) do
    local refs = {}
    if g[2] then table.insert(refs, {unit_id = g[2], getType = function() return 1 end}) end
    if g[1] then table.insert(refs, {unit_id = g[1], getType = function() return 2 end}) end
    local link = {item = {job_type = 9, general_refs = refs}}
    last.next = link
    last = link
end
df.global.world.jobs = {list = head}
env.dfhack.job = {removeJob = function(j)
    if W.remove_fails then return false end
    for _, u in ipairs(W.units) do
        if u.job and u.job.current_job == j then u.job.current_job = nil end
    end
    table.insert(W.removed, j.job_type)
    return true
end}
"""


def hosp(lua, env, w, give=None):
    lua.execute(HOSP, env, w, T(lua, give or []))


# --- 1. classify: a patient up and walking is not 'injured' ------------------------------------

@test("classify (B: Zutthan up at his crafts): a patient who can stand and isn't resting falls through")
def _():
    lua, env, w = world()
    c = lambda **f: env.classify(T(lua, f))
    here = dict(wells_group=5, timer=74000)
    assert c(patient=True, can_stand=True, job="MakeCrafts", **here) == "unknown"
    assert c(patient=True, can_stand=True, **here) == "unknown"
    assert c(patient=True, job="MakeCrafts", **here) == "unknown"            # can_stand unread: the job shows them up
    assert c(patient=True, can_stand=True, cancel={"why": "Dangerous terrain"}, **here) == "cancelled"
    assert c(patient=True, can_stand=True, cancel={"why": "Could not find path"}, **here) == "no_path"
    assert c(patient=True, can_stand=True, timer=74000, drink_elsewhere=40) == "no_path"
    assert c(was_patient=True, can_stand=True, **here) == "unknown"


@test("classify: resting, lying, unable to stand, unconscious or 'too injured': still 'injured'")
def _():
    lua, env, w = world()
    c = lambda **f: env.classify(T(lua, f))
    here = dict(wells_group=5, timer=74000)
    assert c(patient=True, resting=True, can_stand=True, job="Rest", **here) == "injured"   # B: Uvash in bed
    assert c(patient=True, can_stand=False, **here) == "injured"
    assert c(patient=True, lying=True, job="MakeCrafts", **here) == "injured"
    assert c(was_patient=True, resting=True, **here) == "injured"
    assert c(was_patient=True, can_stand=False, **here) == "injured"
    assert c(can_stand=False, **here) == "injured"                       # not a patient, but can't walk to it
    assert c(unconscious=True, can_stand=False, **here) == "injured"
    assert c(patient=True, can_stand=True, cancel={"why": "Too injured"}, **here) == "injured"
    assert c(patient=True, **here) == "injured"                          # nothing read: not known to be up
    # the reasons before still come first
    assert c(patient=True, can_stand=False, jailed=True, **here) == "jailed"
    assert c(patient=True, resting=True, timer=74000) == "no_drink"


# --- 2. the report's rows ------------------------------------------------------------------------

@test("report (B 24 Nov): Zutthan up at MakeCrafts is a walking patient, not injured; Uvash resting in bed is")
def _():
    lua, env, w = world()
    w.zgroup[160] = 1
    w.zgroup[165] = 1
    w.well(T(lua, {"centerx": 110, "centery": 140, "z": 160}))
    w.well(T(lua, {"centerx": 110, "centery": 140, "z": 165}))
    dwarf(lua, w, 18458, 74000, pos={"x": 100, "y": 150, "z": 165}, name={"full": "Zutthan"},
          health={"flags": CARE}, status2=LEGS, job={"current_job": {"job_type": CRAFTS}})
    dwarf(lua, w, 17126, 74500, pos=UVASH_AT, name={"full": "Uvash"},
          health={"flags": CARE}, status2=LEGS, job={"current_job": {"job_type": REST}})
    _, by = rows(env)
    z = by[18458]
    assert z["reason"] == "unknown" and z["patient"] is True, z
    assert z["can_stand"] is True and z["walking_patient"] is True and z["job"] == "MakeCrafts", z
    u = by[17126]
    assert u["reason"] == "injured" and u["resting"] is True and u["can_stand"] is True, u
    assert u.get("walking_patient") is None, u
    # the snapshot still holds Zutthan a patient (was_patient goes on reading it)
    assert py(w.site["ai-overseer/thirst"])["snap"]["18458"]["patient"] is True


@test("report: no leg to stand on, or unconscious: can_stand false, injured; unread legs and no job: injured")
def _():
    lua, env, w = world()
    w.zgroup[165] = 1
    w.well(T(lua, {"centerx": 110, "centery": 140, "z": 165}))
    at = {"x": 100, "y": 150, "z": 165}
    dwarf(lua, w, 1, 60000, pos=at, health={"flags": CARE}, status2={"limbs_stand_max": 2, "limbs_stand_count": 0})
    dwarf(lua, w, 2, 60000, pos=at, counters={"death_id": -1, "unconscious": 30}, status2=LEGS)
    dwarf(lua, w, 3, 60000, pos=at, health={"flags": CARE}, flags1={"on_ground": True},
          status2={"limbs_stand_max": 2, "limbs_stand_count": 1})                  # one leg, crawling
    dwarf(lua, w, 4, 60000, pos=at, health={"flags": CARE})                       # nothing to read
    dwarf(lua, w, 5, 60000, pos=at, status2=LEGS)                                 # not a patient at all
    _, by = rows(env)
    assert by[1]["reason"] == "injured" and by[1]["can_stand"] is False, by[1]
    assert by[2]["reason"] == "injured" and by[2]["can_stand"] is False and by[2]["unconscious"] is True, by[2]
    assert by[3]["reason"] == "injured" and by[3]["can_stand"] is False, by[3]
    assert by[4]["reason"] == "injured" and by[4].get("can_stand") is None and by[4].get("walking_patient") is None
    assert by[5]["reason"] == "unknown" and by[5]["can_stand"] is True and by[5].get("walking_patient") is None


@test("report: a patient once (was_patient), flags clear now, up and walking: walking_patient, not injured")
def _():
    lua, env, w = world()
    w.zgroup[165] = 1
    w.well(T(lua, {"centerx": 110, "centery": 140, "z": 165}))
    u = dwarf(lua, w, 1, 30000, pos={"x": 100, "y": 150, "z": 165}, health={"flags": CARE},
              job={"current_job": {"job_type": REST}}, status2=LEGS)
    _, by = rows(env)
    assert by[1]["reason"] == "injured", by[1]
    u.health = T(lua, {"flags": {}})
    u.job = T(lua, {"current_job": {"job_type": CRAFTS}})
    u.counters2.thirst_timer = 52000
    _, by = rows(env)
    assert by[1]["was_patient"] is True and by[1]["walking_patient"] is True and by[1]["reason"] == "unknown", by[1]


# --- 3. thirst_patient: why no water comes ---------------------------------------------------------

def uvash(lua, w, **kw):
    kw.setdefault("job", {"current_job": {"job_type": REST}})
    kw.setdefault("status2", LEGS)
    kw.setdefault("pos", UVASH_AT)
    return dwarf(lua, w, 17126, 74500, name={"full": "Uvash"}, health={"flags": CARE}, **kw)


@test("patient_help (B: Uvash in zone #1342's bed): resting, can stand, in bed, the hospital's buckets, no GiveWater")
def _():
    lua, env, w = world()
    hosp(lua, env, w, give=[[False, 30]])                 # one GiveWater job, for nobody named
    env.df.unit_labor = T(lua, {"FEED_WATER_CIVILIANS": 77})
    w.zgroup[160] = 1
    w.well(T(lua, {"centerx": 110, "centery": 140, "z": 160}))
    for i in range(3):
        dwarf(lua, w, 30 + i, 0, status={"labors": {77: True}})
    dwarf(lua, w, 40, 0, status={"labors": {77: True}}, job={"current_job": {"job_type": CRAFTS}})
    uvash(lua, w)
    r = py(env.patient_help(17126, False))
    assert r["ok"] and r["resting"] is True and r["can_stand"] is True and r["in_bed"] is True, r
    assert r["hospital"] == {"id": 12, "zone_id": 1342, "count_buckets": 2, "desired_buckets": 2}, r
    assert r["give_water_jobs"] == 1 and r["give_water_for_them"] == 0, r
    assert r["carriers"] == 4 and r["carriers_free"] == 3, r
    assert r["wells_here"] == 1 and r.get("got_up") is None, r      # the old fields kept
    assert not list(w.removed.values()), "nothing ended without get_up"


@test("patient_help: a GiveWater job naming them; out of bed and out of the hospital: in_bed false, no hospital")
def _():
    lua, env, w = world()
    hosp(lua, env, w, give=[[17126, 31], [False, 32]])
    uvash(lua, w)
    r = py(env.patient_help(17126, True))
    assert r["give_water_jobs"] == 2 and r["give_water_for_them"] == 1, r
    lua, env, w = world()
    hosp(lua, env, w, give=[[99, 17126]])                 # they are the worker, not the patient
    uvash(lua, w, pos={"x": 10, "y": 10, "z": 100}, job={"current_job": {"job_type": CRAFTS}})
    r = py(env.patient_help(17126, True))
    assert r["resting"] is False and r["in_bed"] is False and r.get("hospital") is None, r
    assert r["give_water_jobs"] == 1 and r["give_water_for_them"] == 0, r


@test("patient_help: the hospital reads nothing in the old fake fort (no buildings API): fields left out, ok")
def _():
    lua, env, w = world()
    w.zgroup[163] = 1
    dwarf(lua, w, 7, 50000, pos={"x": 112, "y": 155, "z": 163}, health={"flags": CARE})
    r = py(env.patient_help(7, False))
    assert r["ok"] and r.get("in_bed") is None and r.get("hospital") is None and r["give_water_jobs"] == 0, r
    assert r.get("can_stand") is None and r["resting"] is False and r["carriers_free"] == 0, r


# --- 4. get_up ---------------------------------------------------------------------------------------

@test("get_up (Uvash resting, can stand): a dry run plans it and ends nothing; then the Rest job is ended")
def _():
    lua, env, w = world()
    hosp(lua, env, w)
    u = uvash(lua, w)
    r = py(env.patient_help(17126, True, True))
    assert r["ok"] and r["dry_run"] is True and r["got_up"] is True, r
    assert not list(w.removed.values()) and u.job.current_job is not None
    r = py(env.patient_help(17126, False, True))
    assert r["ok"] and r["got_up"] is True and r.get("dry_run") is None, r
    assert list(w.removed.values()) == [REST] and u.job.current_job is None


@test("get_up refused: not resting, can't stand, legs unread; nothing changed (the hospital burrow kept)")
def _():
    lua, env, w = world()
    hosp(lua, env, w)
    lua.execute(r"""
local env, W = ...
W.assigned = {}
env.dfhack.burrows.setAssignedUnit = function(b, u, on) table.insert(W.assigned, u.id) end
local old = env.reqscript
env.reqscript = function(name)
    if name == 'ai-society-burrows' then return {HOSPITAL_BURROW_KEY = 'ai-overseer/hospital-burrow'} end
    return old(name)
end
""", env, w)
    w.burrows[1] = T(lua, {"id": 45, "name": "AI hospital", "tiles": {}})
    w.site["ai-overseer/hospital-burrow"] = T(lua, {"burrow_id": 45, "members": {"17126": 1}, "out": {}})
    u = uvash(lua, w, job={"current_job": {"job_type": CRAFTS}}, burrows=[45])
    r = py(env.patient_help(17126, False, True))
    assert r["rejected"] and not r["ok"] and "not resting" in r["error"] and r.get("got_up") is None, r
    assert r["can_stand"] is True and r.get("lifted") is None, r
    u.job = T(lua, {"current_job": {"job_type": REST}})
    u.status2 = T(lua, {"limbs_stand_max": 2, "limbs_stand_count": 0})
    r = py(env.patient_help(17126, False, True))
    assert r["rejected"] and "cannot stand" in r["error"] and r["resting"] is True, r
    u.status2 = None
    r = py(env.patient_help(17126, False, True))
    assert r["rejected"] and "could not be read" in r["error"], r
    assert not list(w.removed.values()) and not list(w.assigned.values())
    assert "17126" in py(w.site["ai-overseer/hospital-burrow"])["members"]


@test("get_up: DF refuses to end the Rest job: ok false, said, got_up not claimed")
def _():
    lua, env, w = world()
    hosp(lua, env, w)
    w.remove_fails = True
    uvash(lua, w)
    r = py(env.patient_help(17126, False, True))
    assert r["ok"] is False and "could not be ended" in r["error"] and r.get("got_up") is None, r


# --- 5. the bridge ---------------------------------------------------------------------------------

@test("bridge: thirst_patient passes get_up (true or false only) beside the dry run")
def _():
    b = bridge_hub_src()
    i = b.index("thirst_patient = function(a)")
    seg = b[i:i + 700]
    assert "patient_help(id, a.dry_run == true, a.get_up == true)" in seg, seg
    assert re.search(r"a\.get_up ~= nil and type\(a\.get_up\) ~= 'boolean'", seg), seg


if __name__ == "__main__":
    finish()
