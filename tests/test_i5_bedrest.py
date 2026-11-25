"""(item5) The wounded who are up and working put to bed for DF's doctors.

B, 24 Nov: Zutthan waited 126 days "for immobilize, dressing, surgery", up
and working, and died; the chief medical dwarf, two surgeons, a doctor and
the militia captain walked about with infected wounds DF had diagnosed years
before and asked nothing for (probe i5-health-flags: every infected wound and
part flagged diagnosed, no rq_ flag, needs_healthcare false). The bridge
(lua/ai-health.lua bed_rest) gives a patient DF asked a treatment for the
special Rest job dwarfvet gives an injured animal; a heavy chronic infection
is a trial (made undiagnosed, rq_diagnosis set, undone when DF asks nothing);
the last dwarf able to diagnose stays up, and a healthy citizen is given the
DIAGNOSE labour when nobody healthy has it. The planner's rule:
brain/planner_bedrest.py; the hospital's last healthy post holder kept
(planner_health._doctor_patient_rule).

The Lua tests need lupa (they run on the PC); the planner tests run anywhere.

    python tests/test_i5_bedrest.py
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

from planner import PLANNER_CONFIG, plan  # noqa: E402
from planner_core import Memory  # noqa: E402
from planner_bedrest import _bed_rest_rule, rediag_allowed  # noqa: E402
from planner_health import _doctor_patient_rule  # noqa: E402
import hold_classes  # noqa: E402

HEALTH_RAW = (ROOT / "lua" / "ai-health.lua").read_text(encoding="utf-8")
CATALOG = (ROOT / "lua" / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
ACTIONS_FORT = (ROOT / "lua" / "ai-bridge-actions-fort.lua").read_text(encoding="utf-8")
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG


def fort(inf):
    s = copy.deepcopy(BASE)
    s["infection"] = inf
    return s


# B live, 24 Nov 22:22 (infection section), with the bed-rest part as the new bridge reports it
B_BED = {"treat_waiting": 0, "rediag_waiting": 2, "ready_treat": 0, "ready_rediag": 2, "able_diagnosers": 14,
         "healthy_diagnosers": 12, "sleeping": 0, "trials": 0, "stats": {},
         "who": [{"id": 17255, "name": "Fath Shemnish, Doctor", "kind": "rediag", "load": 105, "needs": [],
                  "healer": True, "why": "up, at work (DumpItem)"},
                 {"id": 17268, "name": "Astesh Fikodam, militia captain", "kind": "rediag", "load": 91, "needs": [],
                  "why": "up, at work (FillPond)"}]}
B_INF = {"infected": 8, "untreated": 8, "idle_untreated": 0, "not_patients": 8, "chronic": 8, "beds": 22,
         "free_beds": 11, "hospital_zones": 4, "cleaners": 22, "diagnosers": 14, "max_load": 105, "sleeping": 0,
         "worst": [{"id": 17255, "name": "Fath", "load": 105, "diagnosed": True}], "bed": B_BED}


def run(inf, cfg=CFG):
    props, notes = [], []
    _bed_rest_rule(fort(inf), cfg, props, notes)
    return [p for p in props if p.rule == "bed_rest"], notes


# --- the planner ----------------------------------------------------------------------------

@test("B's chronic infections (every infected wound diagnosed, nothing asked): one trial at a time, the note says "
      "who waits and why")
def _():
    got, notes = run(B_INF)
    assert len(got) == 1, (got, notes)
    a = got[0].action
    assert a == {"type": "bed_rest", "max": 1, "cap": 3, "keep_free": 2, "rediag": True}, a
    assert got[0].priority == 3 and "trial" in got[0].reason, got[0]
    n = [x for x in notes if "heavy infection DF counts treated" in x]
    assert n and "Fath Shemnish, Doctor (old infection, load 105, a healer): up, at work (DumpItem)" in n[0], notes


@test("a patient DF asked a treatment for, up and working: put to bed first; raised while one bleeds")
def _():
    bed = dict(B_BED, treat_waiting=2, ready_treat=2,
               who=[{"id": 1, "name": "Zutthan Azinmeng, Miner", "kind": "treat", "load": 20,
                     "needs": ["immobilize", "dressing", "surgery"], "why": "up, at work (Mine)"}] + B_BED["who"])
    got, notes = run(dict(B_INF, bed=bed))
    assert got and got[0].action["max"] == 2 and got[0].priority == 2, got
    assert "Zutthan Azinmeng" in got[0].reason, got[0].reason
    assert any("Zutthan Azinmeng, Miner (needs immobilize, dressing, surgery): up, at work (Mine)" in n for n in notes)
    bed["who"][0]["load"] = 340
    got, _ = run(dict(B_INF, bed=bed))
    assert got[0].priority == 1, got


@test("the trial stops after bed_rest_rediag_give_up failures with none helped (the note says so); a help keeps it")
def _():
    bed = dict(B_BED, stats={"rediag_failed": 3, "rediag_tried": 3})
    got, notes = run(dict(B_INF, bed=bed))
    assert not got and any("trial is stopped (3 failed, none helped)" in n for n in notes), (got, notes)
    bed = dict(B_BED, stats={"rediag_failed": 3, "rediag_helped": 1})
    assert rediag_allowed(bed, CFG) and run(dict(B_INF, bed=bed))[0]
    assert not rediag_allowed(B_BED, dict(CFG, bed_rest_rediag=False))
    bed = dict(B_BED, trials=1)                       # one already in bed: no second trial
    assert not run(dict(B_INF, bed=bed))[0]


@test("no bed to spare, or the cap reached: nothing asked, the note says why; no hospital: nothing")
def _():
    bed = dict(B_BED, treat_waiting=1, ready_treat=1)
    got, notes = run(dict(B_INF, bed=bed, free_beds=2))
    assert not got and any("2 hospital bed(s) free, 2 kept" in n for n in notes), notes
    got, notes = run(dict(B_INF, bed=dict(bed, sleeping=2), sleeping=1))
    assert not got and any("3 of the AI's sleepers in bed already (at most 3)" in n for n in notes), notes
    got, _ = run(dict(B_INF, bed=bed, hospital_zones=0))
    assert not got


@test("nobody healthy can diagnose: the bridge is asked to give the labour even with nobody to put to bed")
def _():
    bed = dict(B_BED, ready_rediag=0, rediag_waiting=0, who=[], healthy_diagnosers=0,
               healer_candidate={"id": 9, "skill": 2})
    got, notes = run(dict(B_INF, bed=bed))
    assert got and got[0].action["max"] == 1 and "labour given" in got[0].reason and got[0].priority == 2, got
    assert any("no healthy dwarf able to diagnose" in n for n in notes)
    got, notes = run(dict(B_INF, bed=dict(bed, healer_candidate=None)))
    assert not got and any("no healthy citizen can take it" in n for n in notes)


@test("an older bridge (no bed part) or a failed survey: no proposal (the failure said)")
def _():
    inf = {k: v for k, v in B_INF.items() if k != "bed"}
    assert run(inf) == ([], [])
    got, notes = run(dict(B_INF, bed={"error": "boom"}))
    assert not got and any("bed-rest survey failed (boom)" in n for n in notes)


@test("plan(): the rule runs under the infection gate; its class, theme, words and config are there")
def _():
    props, _ = plan(fort(B_INF), Memory())
    assert any(p.rule == "bed_rest" for p in props), [p.rule for p in props]
    assert hold_classes.RULE_CLASS.get("bed_rest") and hold_classes.ACTION_CLASS.get("bed_rest")
    src = (ROOT / "brain" / "overseer_words.py").read_text(encoding="utf-8")
    assert '"bed_rest":' in src and 't == "bed_rest"' in src
    for k in ("bed_rest_cooldown_ticks", "bed_rest_max", "bed_rest_cap", "bed_rest_keep_free", "bed_rest_rediag",
              "bed_rest_rediag_give_up"):
        assert k in CFG, k


@test("the hospital's post holders all patients: the healthiest still up keeps his post; one lying there doesn't")
def _():
    s = fort({})
    s["health"] = {"hospital": [{"id": 4, "staff": [{"post": "DOCTOR", "unit_id": 10},
                                                    {"post": "SURGEON", "unit_id": 11}], "zones": []}],
                   "patients": [{"id": 10, "name": "Fath", "needs": ["dressing", "surgery"]},
                                {"id": 11, "name": "Aban", "needs": ["cleaning"]}]}
    props = []
    _doctor_patient_rule(s, props)
    assert [p.action["unit_id"] for p in props] == [10], props          # Aban (one need) keeps his
    s["health"]["patients"][1]["in_hospital"] = True                     # Aban lies in the hospital now
    s["health"]["patients"][0]["in_hospital"] = True
    props = []
    _doctor_patient_rule(s, props)
    assert [p.action["unit_id"] for p in props] == [10], props          # nobody up: given back as before
    s["health"]["patients"] = [{"id": 11, "name": "Aban", "needs": ["cleaning"]}]   # Fath healthy
    props = []
    _doctor_patient_rule(s, props)
    assert [p.action["unit_id"] for p in props] == [11], props          # a healthy holder stands: as before


# --- the bridge's text --------------------------------------------------------------------------

@test("the bridge: bed_rest in the action table and the dry-run list, bounded, passed to ai-health")
def _():
    assert "bed_rest = act_bed_rest" in CATALOG
    dry = CATALOG[CATALOG.index("DRY_OK"):]
    assert "'bed_rest'" in dry
    body = ACTIONS_FORT[ACTIONS_FORT.index("function act_bed_rest"):]
    assert "int_in(a.max or 2, 1, 5)" in body and "reqscript('ai-health').bed_rest(" in body
    assert "rediagnose" not in CATALOG


@test("ai-health: the trial's flags are recorded before they change and put back on failure; the survey reports bed")
def _():
    start = HEALTH_RAW[HEALTH_RAW.index("local function trial_start"):HEALTH_RAW.index("local function trial_undo")]
    assert start.index("table.insert(rec, r)") < start.index("p.flags1.diagnosed = false")
    assert "u.health.flags.rq_diagnosis = true" in start and "u.health.flags.needs_healthcare = true" in start
    undo = HEALTH_RAW[HEALTH_RAW.index("local function trial_undo"):HEALTH_RAW.index("local function too_dry")]
    assert "w.flags.diagnosed = true" in undo and "u.health.flags.rq_diagnosis = false" in undo
    survey = HEALTH_RAW[HEALTH_RAW.index("function survey("):HEALTH_RAW.index("local function give_rest")]
    assert "pcall(bed_survey, zones, staff, citizens, txt)" in survey
    assert len(HEALTH_RAW.encode("utf-8")) + HEALTH_RAW.count("\n") < 58 * 1024


# --- the bridge in a Lua engine (lupa: on the PC) ----------------------------------------------

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

if LuaRuntime is not None:
    from lua_modules_util import module_src  # noqa: E402

    HEALTH = module_src("ai-health.lua")
    _care = ast.parse((ROOT / "tests" / "test_care.py").read_text(encoding="utf-8"))
    _consts = {}
    for _n in _care.body:
        if isinstance(_n, ast.Assign) and isinstance(_n.targets[0], ast.Name) and _n.targets[0].id in (
                "VEC", "HEALTH_FAKE"):
            _v = _n.value
            if isinstance(_v, ast.BinOp):            # VEC + r"""..."""
                _consts[_n.targets[0].id] = ("VEC", _v.right.value)
            else:
                _consts[_n.targets[0].id] = (None, _v.value)
    _fake = _consts["VEC"][1] + _consts["HEALTH_FAKE"][1]
    # (item5) the extras: treatments asked, chronic wounds with parts, thirst, a Rest job, DIAGNOSE given
    _EXTRA = r"""
local LABOR = {given = {}}
LABOR.give_labor = function(u, tok) table.insert(LABOR.given, u.id); u.status.labors[2] = true; return true end
env.LABOR_FAKE = LABOR
env.reqscript = function(n) if n == 'ai-labor' then return LABOR end error('reqscript ' .. tostring(n)) end
for i, su in ipairs(spec.units) do
    local u = units[i]
    for _, k in ipairs(su.rq or {}) do u.health.flags[k] = true end
    if su.chronic then
        u.body.wounds = {{id = 50 + i, flags = {infection = true, diagnosed = true},
                          parts = {{flags1 = {diagnosed = true}}, {flags1 = {diagnosed = false}}}}}
        u.health.flags.needs_healthcare = false
    end
    if su.thirst then u.counters2 = {thirst_timer = su.thirst, hunger_timer = 0} end
    if su.rest then u.job.current_job = {id = 4000 + i, job_type = REST, pos = {x = 9, y = 9, z = 0}} end
end
local function fresh()"""
    assert "local function fresh()" in _fake
    _fake = _fake.replace("local function fresh()", _EXTRA, 1)

    def health(units, beds=((1, 1, 0), (2, 1, 0), (3, 1, 0), (4, 1, 0), (6, 1, 0), (7, 1, 0)), **kw):
        lua = LuaRuntime(unpack_returned_tuples=True)

        def lt(v):
            if isinstance(v, dict):
                return lua.table_from({k: lt(x) for k, x in v.items()})
            if isinstance(v, (list, tuple)):
                return lua.table_from([lt(x) for x in v])
            return v
        return lua.execute(_fake, HEALTH, lt({"units": units, "beds": list(beds), **kw}))

    DAY = 1200
    DOC = {"id": 20, "x": 50, "diagnose": True}                      # a healthy diagnoser, up

    def sent_ids(r):
        return [x.unit_id for x in r.sent.values()] if r.sent else []

    @test("lua: a patient DF asked a treatment for, at work, is taken off his job and given the Rest job in a bed")
    def _():
        rows = [{"id": 1, "x": 50, "busy": True, "rq": ["rq_immobilize", "rq_dressing"]}, DOC]
        env, units, made, _, _ = health(rows)
        b = env.survey().bed
        assert (b.treat_waiting, b.ready_treat, b.able_diagnosers, b.healthy_diagnosers) == (1, 1, 1, 1), dict(b)
        assert b.who[1].id == 1 and b.who[1].why.startswith("up, at work"), dict(b.who[1])
        r = env.bed_rest(2, False, None, 3, 2, False)
        assert r.ok and sent_ids(r) == [1] and r.sent[1].kind == "treat", dict(r)
        assert units[1].job.current_job.job_type == 7 and made[1].flags.special
        st = env.site_data["ai-overseer/bed-rest"].sent["1"]
        assert st.kind == "treat" and st.sig == "rq_immobilize,rq_dressing", dict(st)

    @test("lua: the last dwarf able to diagnose stays up; with another able, the healer goes first")
    def _():
        rows = [{"id": 1, "x": 50, "rq": ["rq_surgery"], "diagnose": True},
                {"id": 2, "x": 50, "rq": ["rq_surgery"], "load": 200}]
        env, _, _, _, _ = health(rows)
        r = env.bed_rest(1, False, None, 3, 2, False)
        assert r.ok and sent_ids(r) == [2] and [k.unit_id for k in r.kept.values()] == [1], dict(r)
        env, _, _, _, _ = health(rows + [DOC])
        r = env.bed_rest(1, False, None, 3, 2, False)
        assert r.ok and sent_ids(r) == [1], dict(r)                  # the healer first

    @test("lua: the re-diagnosis trial: flags cleared, the Rest job; nothing asked in 3 days: every flag put back")
    def _():
        rows = [{"id": 1, "x": 50, "infected": True, "chronic": True, "load": 105},
                {"id": 2, "x": 50, "infected": True, "chronic": True, "load": 91}, DOC]
        env, units, made, _, removed = health(rows)
        b = env.survey().bed
        assert (b.rediag_waiting, b.ready_rediag) == (2, 2), dict(b)
        r = env.bed_rest(2, False, None, 3, 2, False)
        assert not r.ok and len(made) == 0, dict(r)                  # the trial not allowed: nobody
        r = env.bed_rest(2, False, None, 3, 2, True)
        assert r.ok and sent_ids(r) == [1], dict(r)                   # one trial at a time, the heavier
        w = units[1].body.wounds[1]
        assert not w.flags.diagnosed and not w.parts[1].flags1.diagnosed
        assert units[1].health.flags.rq_diagnosis and units[1].health.flags.needs_healthcare
        assert env.survey().bed.trials == 1
        env.df["global"].cur_year_tick = 1000 + 3 * DAY
        b = env.survey().bed
        assert w.flags.diagnosed and w.parts[1].flags1.diagnosed and not w.parts[2].flags1.diagnosed
        assert not units[1].health.flags.rq_diagnosis and not units[1].health.flags.needs_healthcare
        assert units[1].job.current_job is None and len(removed) == 1
        assert b.stats.rediag_failed == 1 and b.stats.rediag_tried == 1 and b.trials == 0, dict(b.stats)
        r = env.bed_rest(2, False, None, 3, 2, True)
        assert r.ok and sent_ids(r) == [2], dict(r)                   # dwarf 1 waits out his cooldown

    @test("lua: the trial helped (DF asked a treatment): a patient in bed, kept; every treatment given: got up")
    def _():
        rows = [{"id": 1, "x": 50, "infected": True, "chronic": True, "load": 105}, DOC]
        env, units, _, _, removed = health(rows)
        env.bed_rest(1, False, None, 3, 2, True)
        f = units[1].health.flags
        f.rq_diagnosis, f.rq_cleaning = False, True
        b = env.survey().bed
        assert b.stats.rediag_helped == 1 and b.sleeping == 1 and b.trials == 0, dict(b.stats)
        assert env.site_data["ai-overseer/bed-rest"].sent["1"].kind == "treat"
        f.rq_cleaning = False
        b = env.survey().bed
        assert b.stats.treated == 1 and b.sleeping == 0 and len(removed) == 1

    @test("lua: no treatment given in 14 days: got up; a sleeper grown thirsty: got up to drink; the thirsty never sent")
    def _():
        rows = [{"id": 1, "x": 50, "rq": ["rq_surgery"]}, {"id": 2, "x": 50, "rq": ["rq_suture"], "thirst": 25000}, DOC]
        env, units, _, _, removed = health(rows)
        r = env.bed_rest(2, False, None, 3, 2, False)
        assert sent_ids(r) == [1], dict(r)
        assert env.survey().bed.who[1].why.startswith("thirsty"), dict(env.survey().bed.who[1])
        env.df["global"].cur_year_tick = 1000 + 14 * DAY
        b = env.survey().bed
        assert b.stats.stalled == 1 and len(removed) == 1, dict(b.stats)
        env, units, _, _, removed = health([dict(rows[0], thirst=1), DOC])
        env.bed_rest(1, False, None, 3, 2, False)
        units[1].counters2.thirst_timer = 31000
        b = env.survey().bed
        assert b.stats.drink_up == 1 and units[1].job.current_job is None

    @test("lua: nobody healthy can diagnose: the labour given (through ai-labor) to the healthy citizen best placed")
    def _():
        rows = [{"id": 1, "x": 50, "rq": ["rq_surgery"], "diagnose": True}, {"id": 3, "x": 50},
                {"id": 4, "x": 50, "squad": 2}]
        env, _, _, _, _ = health(rows)
        b = env.survey().bed
        assert b.healthy_diagnosers == 0 and b.healer_candidate.id == 3, dict(b)
        r = env.bed_rest(1, False, None, 3, 2, False)
        assert r.ok and r.healer.unit_id == 3 and list(env.LABOR_FAKE.given.values()) == [3], dict(r)
        assert sent_ids(r) == [1], dict(r)                            # dwarf 3 can diagnose now: 1 goes to bed

    @test("lua: rest_infected's sleepers share the cap; no hospital: rejected; a dry run changes nothing")
    def _():
        rows = [{"id": 1, "x": 50, "rq": ["rq_surgery"]}, DOC]
        env, units, made, _, _ = health(rows)
        d = env.bed_rest(1, True, None, 3, 2, False)
        assert d.ok and d.dry_run and sent_ids(d) == [1] and len(made) == 0, dict(d)
        env, _, _, _, _ = health(rows, no_hospital=True)
        assert "no hospital zone" in env.bed_rest(1, False, None, 3, 2, False).error

    @test("lua (pure): bed_picks puts the treatments first, healers first and the healthiest of them first")
    def _():
        lua = LuaRuntime(unpack_returned_tuples=True)
        env = lua.execute("local src = ...; local e = setmetatable({}, {__index = _G}); "
                          "assert(load(src, 'h', 't', e))(); return e", HEALTH)

        def c(**kw):
            kw["rq"] = lua.table_from(kw.get("rq", []))
            return lua.table_from(kw)
        rows = lua.table_from([c(id=1, rq=["rq_surgery"], load=300), c(id=2, rq=["rq_surgery", "rq_suture"],
                                                                              diagnoser=True),
                               c(id=3, rq=["rq_suture"], diagnoser=True), c(id=4, chronic=True, load=500),
                               c(id=5, diagnoser=True), c(id=6, rq=["rq_dressing"], soldier=True)])
        out, kept = env.bed_picks(rows, 10, True, 0)
        assert [x.id for x in out.values()] == [3, 2, 1, 4], [x.id for x in out.values()]
        out, kept = env.bed_picks(rows, 10, False, 0)
        assert [x.id for x in out.values()] == [3, 2, 1], [x.id for x in out.values()]
        out, kept = env.bed_picks(rows, 10, True, 1)                    # a trial in bed already
        assert 4 not in [x.id for x in out.values()]


if __name__ == "__main__":
    finish()
