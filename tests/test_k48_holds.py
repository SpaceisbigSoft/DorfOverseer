"""(0.105.48, K5) Crisis and recovery holds by one table (brain/hold_classes.py).
No game needed.

    python tests/test_k48_holds.py

  * every rule the planner can make and every bridge action kind is in
    exactly one class (survival, defence, expansion); no stale names;
  * no emergency, steer-protected or crisis recovery rule is expansion;
  * recovery lets the floodgate's shut/retire/recheck, a vampire's
    expulsion, traps, cavern doors, wild_hunt through; holds the expansion
    rules it missed; a start_project's rule outranks its kind;
  * crisis holds the same expansion, not squad_make; a Jeweler's level is
    not boosted as recovery;
  * soldiers away don't start recovery; no migrant wave into a siege, an
    alert or a dry fort.
"""

from __future__ import annotations

import ast
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))

from harness import test, finish  # noqa: E402
from planner import PLANNER_CONFIG, Memory, plan  # noqa: E402
from planner_core import EMERGENCY, STEER_PROTECTED, LIMIT_EXEMPT, Proposal  # noqa: E402
import crisis  # noqa: E402
import hold_classes as H  # noqa: E402
import planner_recovery as R  # noqa: E402

CFG = PLANNER_CONFIG
DAY = 1200
YEAR = 336 * DAY
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def P(rule, **action):
    return Proposal(rule, action, "why", 5)


# ---- the names ------------------------------------------------------------------------------

def planner_rules() -> set:
    """Every rule name a Proposal(...) in brain/ can carry: literals, module
    constants, and the few made from a kind (cleanup, quick, waterworks)."""
    names, dynamic = set(), []
    for f in sorted((ROOT / "brain").glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        consts = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        consts[t.id] = n.value.value
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", None)) == "Proposal"
                    and n.args):
                a = n.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    names.add(a.value)
                elif isinstance(a, ast.Name) and a.id in consts:
                    names.add(consts[a.id])
                else:
                    dynamic.append((f.name, ast.unparse(a)))
    import planner_cleanup
    import planner_water
    for kind in planner_cleanup.CLEANUP_ACTIONS.values():
        names |= {f"cleanup_{kind}", f"cleanup_{kind}_dry"}
    names |= {"quick_temple", "quick_tavern"}
    names |= {f"waterworks_{k}" for k in planner_water.WORK_WORDS}
    names.add("strategist")
    known_dynamic = {("planner_cleanup.py", "f'cleanup_{kind}_dry'"), ("planner_cleanup.py", "f'cleanup_{kind}'"),
                     ("planner_locations.py", "'quick_' + kind"), ("planner_water.py", "f'waterworks_{kind}'"),
                     ("planner_select.py", "p.rule"), ("planner_holdfast.py", "first.rule"),
                     ("planner_industry.py", "p.rule"), ("review.py", "rule")}
    new = sorted(set(dynamic) - known_dynamic)
    assert not new, f"a rule name made at run time this test doesn't know: {new}"
    return names


def bridge_actions() -> set:
    src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    i = src.index("ACTIONS = {")
    body = src[i:src.index("\n}\n", i)]
    return set(re.findall(r"(?m)^    ([a-z_0-9]+)\s*=", body)) | set(re.findall(r",\s*([a-z_0-9]+)\s*=\s*act_", body))


@test("every planner rule is in exactly one class; the table names no rule the planner can't make")
def _():
    rules = planner_rules()
    assert len(rules) > 300, len(rules)
    unclassed = sorted(r for r in rules if r not in H.RULE_CLASS)
    assert not unclassed, f"rules in no class (add them to brain/hold_classes.py): {unclassed}"
    seen: dict = {}
    for cls, names in H.RULE_SETS.items():
        for n in names:
            assert n not in seen, f"{n} is both {seen[n]} and {cls}"
            seen[n] = cls
    stale = sorted(set(H.RULE_CLASS) - rules)
    assert not stale, f"classed names no Proposal makes: {stale}"


@test("every bridge action kind is in exactly one class; the table names no kind the bridge lacks")
def _():
    acts = bridge_actions()
    assert len(acts) > 200 and "call_migrants" in acts and "hunt_send" in acts, len(acts)
    unclassed = sorted(a for a in acts if a not in H.ACTION_CLASS)
    assert not unclassed, f"action kinds in no class (add them to brain/hold_classes.py): {unclassed}"
    seen: dict = {}
    for cls, names in H.ACTION_SETS.items():
        for n in names:
            assert n not in seen, f"{n} is both {seen[n]} and {cls}"
            seen[n] = cls
    stale = sorted(set(H.ACTION_CLASS) - acts)
    assert not stale, f"classed action kinds the bridge doesn't have: {stale}"


@test("no emergency, steer-protected or crisis recovery rule is expansion")
def _():
    for name, group in (("EMERGENCY", EMERGENCY), ("STEER_PROTECTED", STEER_PROTECTED),
                        ("crisis.RECOVERY_RULES", crisis.RECOVERY_RULES)):
        bad = sorted(r for r in group if H.RULE_CLASS.get(r) == H.EXPANSION)
        assert not bad, (name, bad)
    # LIMIT_EXEMPT holds join_levels (a slot of its own); (0.105.48 merge) and it is survival:
    # cut-off levels joined, the thirst watch's fix, never held in a crisis or recovery
    assert "join_levels" in LIMIT_EXEMPT


# ---- recovery -------------------------------------------------------------------------------

@test("recovery: a waterworks' shut, retire and recheck go; its next step waits (A7 1)")
def _():
    for kind in ("moat", "magma", "power", "pump", "irrigation"):
        rule = f"waterworks_{kind}"
        for flag in ("shut", "retire", "recheck"):
            p = P(rule, type="water_work", kind=kind, **{flag: True})
            assert R.held_in_recovery(p) is None, (rule, flag)
        assert R.held_in_recovery(P(rule, type="water_work", kind=kind)), rule
    assert R.held_in_recovery(P("waterworks_shut", type="water_work", kind="moat", shut=True)) is None
    assert R.held_in_recovery(P("magma_shut", type="water_work", kind="magma", shut=True)) is None


@test("recovery: a vampire sent away, traps, cavern doors, the destroyer gate, wild_hunt, caravan guard go (A7 3)")
def _():
    kept = [P("cursed", type="expel_dwarf", unit_id=5), P("traps", type="place_traps", kind="cage"),
            P("cavern_openings", type="fortify_entrance", entrance_id=3),
            P("cavern_openings", type="build_gate_doors", entrance_id=3),
            P("destroyer_gate", type="fortify_entrance", entrance_id=4),
            P("wild_hunt", type="squad_orders"), P("caravan_guard", type="squad_orders"),
            P("archer_post", type="archer_post"), P("squad_make", type="make_squad")]
    for p in kept:
        assert R.held_in_recovery(p) is None, (p.rule, p.action)
    # Extreme-low Growth's own expulsion still waits
    assert R.held_in_recovery(P("expel", type="expel_dwarf"))


@test("recovery: an expansion rule's workshops level waits; a recovery rule's jail/tavern/temple level goes (A7 4)")
def _():
    for rule in ("paper_shop", "gems", "glass", "industry", "bottleneck", "kiln", "bags"):
        p = P(rule, type="start_project", kind="workshops", shops=["Jewelers"])
        assert R.held_in_recovery(p), rule
    assert R.held_in_recovery(P("reserve_storage", type="start_project", kind="storage"))
    for rule, kind in (("jail_more", "jail"), ("build", "tavern"), ("build", "temple"), ("tavern_urgent", "tavern")):
        assert R.held_in_recovery(P(rule, type="start_project", kind=kind)) is None, (rule, kind)
    # urgent and a mood's level always go, even from an expansion rule
    assert R.held_in_recovery(P("bottleneck", type="start_project", kind="workshops", urgent=True)) is None
    # the bags order itself goes
    assert R.held_in_recovery(P("bags", type="work_order", recipe="bags")) is None


@test("recovery: the expansion rules the old list let through now wait (A7 5)")
def _():
    held = [P("noble_value", type="place_in_zone"),
            P("petition_build", type="start_project", kind="guildhall"),   # (r2h6) petition_answer goes
            P("homes_furnish", type="furnish_liked"), P("landmark", type="build_blueprint"),
            P("landmark_level", type="start_project", kind="dining", landmark=True),
            P("crossing", type="build_crossing"), P("depot", type="deep_depot"), P("quarry", type="quarry"),
            P("ore", type="mine_ore"), P("cavern_logging", type="cavern_logging"),
            P("cavern_farm", type="cavern_farm"), P("library_chest", type="place_in_zone"),
            P("train_hunt", type="train_hunt"), P("herd_breeders", type="herd_breeders"),
            P("tame_wild", type="tame_wild"), P("mission_pets", type="mission_pets"),
            P("mission_way", type="mission_way"), P("fortify_post", type="fortify_post"),
            P("prisoner_pit", type="make_pit"), P("deep_descent", type="cross_cavern"),
            P("training_squad", type="training_squad", mode="make")]
    for p in held:
        assert R.held_in_recovery(p), (p.rule, p.action)
    # the trade depot itself (place_surface) still goes
    assert R.held_in_recovery(P("depot", type="place_surface", what="depot")) is None
    # the strategist's step goes by its kind
    assert R.held_in_recovery(P("strategist", type="hunt_send"))
    assert R.held_in_recovery(P("strategist", type="work_order")) is None


# ---- crisis ---------------------------------------------------------------------------------

@test("crisis: the same expansion waits (keep, grove, noble value, petitions); squad_make and join_levels go (A7 6, 8)")
def _():
    held = [P("keep", type="place_keep"), P("grove", type="keep_grove"), P("noble_value", type="place_in_zone"),
            P("petition_build", type="start_project", kind="guildhall"),
            P("hunt", type="hunt_send"), P("mission", type="send_mission"), P("hall", type="place_hall")]
    # (r2h6) the petition's answer goes: held, it lapsed as "ignored" (C, 16 Nov)
    kept = [P("join_levels", type="join_levels"), P("squad_make", type="make_squad"), P("burial", type="allow_burial"),
            P("hospital", type="work_order"), P("cursed", type="expel_dwarf"),
            P("petition_answer", type="answer_petition")]
    notes: list = []
    out = crisis.apply(held + kept, ["45% unhappy"], notes)
    assert out == kept, [(p.rule, p.action) for p in out]
    assert "squad_make" not in crisis.EXPANSION_RULES
    # crisis and recovery hold the same steps
    for p in held + kept:
        assert bool(crisis.is_expansion(p)) == bool(R.held_in_recovery(p)), (p.rule, p.action)


@test("crisis: a Jeweler's, glass or industry workshops level is expansion, not recovery (A7 7)")
def _():
    for rule in ("gems", "glass", "industry", "paper_shop"):
        p = P(rule, type="start_project", kind="workshops")
        assert crisis.is_expansion(p) and not crisis.is_recovery(p), rule
    hosp = P("build", type="start_project", kind="hospital")
    assert not crisis.is_expansion(hosp) and crisis.is_recovery(hosp)
    jail = P("jail_more", type="start_project", kind="jail")
    assert crisis.is_recovery(jail)
    # crisis_hold_table False: the old 14 names (only the tests comparing main's plan use it)
    old = dict(CFG, crisis_hold_table=False)
    assert crisis.is_expansion(P("squad_make", type="make_squad"), old)
    assert not crisis.is_expansion(P("keep", type="place_keep"), old)
    assert crisis.is_recovery(P("gems", type="start_project", kind="workshops"), old)
    assert CFG["crisis_hold_table"] is True


# ---- recovery's trigger and the migrants ----------------------------------------------------

def st(pop: int, tick: int, year: int = 260, away: int = 0) -> dict:
    s = {"settings": {"traits": {}, "set_pop_cap": True, "fort_goal": "expand"},
         "dwarves": {"total": pop}, "date": {"year": year, "tick": tick}, "society": {"pop_cap": 100}}
    if away is not None:
        s["missions"] = {"squads": [{"id": 1, "members": 10, "away": away}, {"id": 2, "members": 4, "away": 0}]}
    return s


@test("recovery: a squad of 10 away out of 30 is no fall; the same 10 lost is (A7 11)")
def _():
    m = Memory()
    notes: list = []
    R.note_recovery(st(30, 0, away=0), m, CFG, notes)
    R.note_recovery(st(20, 7 * DAY, away=10), m, CFG, notes)
    assert not R.in_recovery(m), (m.recovery, notes)
    R.note_recovery(st(30, 14 * DAY, away=0), m, CFG, notes)     # they came back: not newcomers
    assert m.recovery.get("last_rise") is None, m.recovery
    m2 = Memory()
    R.note_recovery(st(30, 0, away=0), m2, CFG, [])
    R.note_recovery(st(20, 7 * DAY, away=0), m2, CFG, [])
    assert R.in_recovery(m2), m2.recovery
    assert R.soldiers_away({"missions": {"error": "x"}}) == 0 and R.soldiers_away({}) == 0


def mig_state(**extra) -> dict:
    s = {"settings": {"traits": {}, "set_pop_cap": True}, "dwarves": {"total": 10},
         "date": {"year": 262, "tick": 0}, "society": {"pop_cap": 30},
         "migration": {"force": "force", "queued": 0, "hermit_tool": False, "civ": True},
         "others_on_map": {"threats_that_can_reach_dwarves": 0, "threats": []}}
    s.update(extra)
    return s


def fallen() -> Memory:
    m = Memory()
    t = 2 * YEAR - 214 * DAY
    for p in (60, 60, 10):
        R.note_recovery(st(p, t % YEAR, year=260 + t // YEAR, away=None), m, CFG, [])
        t += 7 * DAY
    return m


def mig(s, m):
    props, notes = [], []
    R._migrants_rule(s, m, CFG, props, notes)
    return props, notes


@test("migrants: no wave into an alert, an invader or a surface beast, or a fort short of drink (A7 12)")
def _():
    m = fallen()
    p, n = mig(mig_state(), m)
    assert [x.action for x in p] == [{"type": "call_migrants"}], (p, n)
    waits = [mig_state(civ_alert=True),
             mig_state(others_on_map={"threats_that_can_reach_dwarves": 0,
                                      "threats": [{"id": 1, "invader": True, "can_reach_dwarves": False,
                                                   "layer": "fort_levels"}]}),
             mig_state(others_on_map={"threats_that_can_reach_dwarves": 0,
                                      "threats": [{"id": 2, "can_reach_dwarves": False, "layer": "upper_levels"}]})]
    for s in waits:
        p, n = mig(s, m)
        assert not p and n and "called once" in n[0], (p, n)
    # a cavern beast that can't reach anyone doesn't stop the call
    s = mig_state(others_on_map={"threats_that_can_reach_dwarves": 0,
                                 "threats": [{"id": 3, "can_reach_dwarves": False, "layer": "Cavern1"}]})
    assert mig(s, m)[0]
    # a fort short of drink (the strain's drink line)
    import planner_growth
    real = planner_growth.fort_strain
    planner_growth.fort_strain = lambda s, cfg, held=False, traits=None: ["drink 0.5 a dwarf"]
    try:
        p, n = mig(mig_state(), m)
    finally:
        planner_growth.fort_strain = real
    assert not p and n and "drink 0.5" in n[0], (p, n)


@test("plan(): a fort in recovery keeps no expansion step (the filter runs after every rule)")
def _():
    m = fallen()
    s = copy.deepcopy(BASE)
    props, _notes = plan(s, m)
    bad = [(p.rule, p.action.get("type")) for p in props if H.step_class(p) == H.EXPANSION]
    assert not bad, bad


finish()
