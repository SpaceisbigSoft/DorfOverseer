"""(F2d) One final gate: the player's "never" rules (brain/planner_never.py),
each predicate blocked and allowed, the gate itself, and its one call in
overseer_cycle between select() and the dispatch.

    python tests/test_f2d_never.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from planner_core import Memory, Proposal  # noqa: E402
import planner_never as pn  # noqa: E402


def fort(**kw) -> dict:
    """A small fort: one surface entrance with a hatch on lever 187 and a
    bridge on lever 110, a second surface entrance, 20 adults, 5 soldiers."""
    s = {
        "date": {"year": 250, "tick": 1000},
        "dwarves": {"adults": 20, "total": 22},
        "military": {"soldiers": 5, "gates": [{"id": 187, "linked": True, "shut": False}]},
        "entrances": {"citizens_outside": 4, "entrances": [
            {"id": 1, "kind": "surface", "x": 100, "y": 100, "z": 150, "closed": False,
             "equipment": [{"id": 84, "kind": "hatch", "lever_id": 187, "levers": [187]}],
             "outer": [{"id": 93, "kind": "bridge", "lever_id": 110, "x": 100, "y": 98, "z": 150}]},
            {"id": 2, "kind": "surface", "x": 140, "y": 120, "z": 150, "closed": False,
             "equipment": [{"id": 90, "kind": "door", "levers": []}]},
        ]},
        "others_on_map": {"threats": [], "threats_that_can_reach_dwarves": 0},
        "way_out": {"known": True, "open": True, "cause": {"great": 0, "invaders": 0}},
        "insane": {"list": [{"id": 501, "kind": "raving", "mood": "Raving", "x": 10, "y": 10, "z": 150}]},
        "hazards": {"berserk": []},
        "killers": {"list": []},
        "units": [{"id": 600}, {"id": 601}],
        "settings": {"traits": {}},
    }
    s.update(kw)
    return s


def threat(i, x, y, z=150, **kw) -> dict:
    return dict({"id": i, "hostile": True, "pos": {"x": x, "y": y, "z": z}}, **kw)


def P(action, rule="r", reason="why") -> Proposal:
    return Proposal(rule, action, reason, 1)


# --- never_kill_citizen ---

@test("never_kill_citizen: a kill order on an insane dwarf is blocked")
def _():
    why = pn.never_kill_citizen({"type": "squad_orders", "squad_id": 1, "kill": [501]}, fort(), Memory())
    assert why and "insane" in why, why


@test("never_kill_citizen: a kill order on a sane citizen is blocked")
def _():
    why = pn.never_kill_citizen({"type": "squad_orders", "squad_id": 1, "kill": [900, 600]}, fort(), Memory())
    assert why and "citizen" in why, why


@test("never_kill_citizen: an invader, a berserk citizen, a were changed, and a recall pass")
def _():
    s = fort()
    s["hazards"]["berserk"] = [{"id": 601}]
    s["others_on_map"]["threats"] = [threat(700, 1, 1, transformed=True)]
    s["units"].append({"id": 700})
    m = Memory()
    assert pn.never_kill_citizen({"type": "squad_orders", "squad_id": 1, "kill": [900]}, s, m) is None
    assert pn.never_kill_citizen({"type": "squad_orders", "squad_id": 1, "kill": [601]}, s, m) is None
    assert pn.never_kill_citizen({"type": "squad_orders", "squad_id": 1, "kill": [700]}, s, m) is None
    assert pn.never_kill_citizen({"type": "squad_orders", "squad_id": 1, "clear": True}, s, m) is None


@test("never_kill_citizen: a citizen killer (the killers report) is blocked, a resident one passes")
def _():
    s = fort()
    s["killers"]["list"] = [{"id": 800, "citizen": True, "kind": "vampire"}, {"id": 801, "resident": True}]
    assert pn.never_kill_citizen({"type": "squad_orders", "squad_id": 1, "kill": [800]}, s, Memory())
    assert pn.never_kill_citizen({"type": "squad_orders", "squad_id": 1, "kill": [801]}, s, Memory()) is None


# --- never_sealed_in ---

def last_way(**kw):
    s = fort(**kw)
    s["entrances"]["entrances"][1]["closed"] = True      # the other way out already shut
    return s


@test("never_sealed_in: shutting the last open surface entrance with no live danger is blocked")
def _():
    why = pn.never_sealed_in({"type": "pull_gate", "lever_id": 187}, last_way(), Memory())
    assert why and "map edge" in why, why


@test("never_sealed_in: another way open, or a live danger, lets the close pass")
def _():
    assert pn.never_sealed_in({"type": "pull_gate", "lever_id": 187}, fort(), Memory()) is None
    s = last_way()
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    assert pn.never_sealed_in({"type": "pull_gate", "lever_id": 187}, s, Memory()) is None
    # an opening pull (the AI shut it) is no close
    m = Memory()
    m.gate_closed_by_ai = True
    assert pn.never_sealed_in({"type": "pull_gate", "lever_id": 187}, last_way(), m) is None


@test("never_sealed_in: walling the last surface way for good is blocked; a cavern opening passes")
def _():
    s = last_way()
    assert pn.never_sealed_in({"type": "fortify_entrance", "entrance_id": 1, "style": "sealed"}, s, Memory())
    s["entrances"]["entrances"].append({"id": 3, "kind": "cavern", "x": 1, "y": 1, "z": 100})
    assert pn.never_sealed_in({"type": "fortify_entrance", "entrance_id": 3, "style": "sealed"}, s, Memory()) is None
    assert pn.never_sealed_in({"type": "fortify_entrance", "entrance_id": 1, "style": "plain"}, s, Memory()) is None


# --- gates_close_late ---

@test("gates_close_late: a close with the only danger 30 tiles off and citizens outside is blocked")
def _():
    s = fort()
    s["others_on_map"]["threats"] = [threat(900, 130, 100)]
    why = pn.gates_close_late({"type": "pull_gate", "lever_id": 187}, s, Memory())
    assert why and "12 tiles" in why, why


@test("gates_close_late: danger within 12 tiles, everyone inside, or a great beast: the close passes")
def _():
    s = fort()
    s["others_on_map"]["threats"] = [threat(900, 110, 105)]
    assert pn.gates_close_late({"type": "pull_gate", "lever_id": 187}, s, Memory()) is None
    s = fort()
    s["others_on_map"]["threats"] = [threat(900, 130, 100)]
    s["entrances"]["citizens_outside"] = 0
    assert pn.gates_close_late({"type": "pull_gate", "lever_id": 187}, s, Memory()) is None
    s = fort()
    s["others_on_map"]["threats"] = [threat(900, 199, 199, kinds=["ForgottenBeast"])]
    assert pn.gates_close_late({"type": "pull_gate", "lever_id": 187}, s, Memory()) is None
    s = fort()
    s["others_on_map"]["threats"] = [threat(900, 130, 100)]
    s["way_out"]["cause"]["nearest"] = 8                  # the way_out report's own reading
    assert pn.gates_close_late({"type": "pull_gate", "lever_id": 187}, s, Memory()) is None


@test("gates_close_late: an already shut gate's pull (an open) and other actions pass")
def _():
    s = fort()
    s["military"]["gates"][0]["shut"] = True
    assert pn.gates_close_late({"type": "pull_gate", "lever_id": 187}, s, Memory()) is None
    assert pn.gates_close_late({"type": "open_gates"}, fort(), Memory()) is None


# --- guard_in_every_fort ---

@test("guard_in_every_fort: a trim taking a 20-adult fort from 5 to 2 soldiers is blocked")
def _():
    why = pn.guard_in_every_fort({"type": "squad_trim", "count": 3}, fort(), Memory())
    assert why and "fewer than 3" in why, why
    s = fort()
    s["military"]["soldiers"] = 3
    assert pn.guard_in_every_fort({"type": "squad_release", "unit_id": 5}, s, Memory())


@test("guard_in_every_fort: a trim leaving 3, or in a fort under 15 adults, passes")
def _():
    assert pn.guard_in_every_fort({"type": "squad_trim", "count": 2}, fort(), Memory()) is None
    s = fort()
    s["dwarves"]["adults"] = 12
    assert pn.guard_in_every_fort({"type": "squad_trim", "count": 5}, s, Memory()) is None


# --- strategist_no_cheats ---

@test("strategist_no_cheats: the strategist's call_migrants, insane_water, a probe, raw lua are blocked")
def _():
    for t in ("call_migrants", "insane_water", "thirst_probe", "run_lua", "spawn_units", "free_caravan"):
        assert pn.strategist_no_cheats({"type": t, "by": "strategist"}, fort(), Memory()), t


@test("strategist_no_cheats: the planner's own insane_water and the strategist's work order pass")
def _():
    assert pn.strategist_no_cheats({"type": "insane_water", "units": [501]}, fort(), Memory()) is None
    assert pn.strategist_no_cheats({"type": "work_order", "by": "strategist"}, fort(), Memory()) is None


@test("strategist_no_cheats: gate() knows a strategist proposal by its reason (no by= mark)")
def _():
    p = P({"type": "call_migrants"}, rule="strategist", reason="strategist: more hands")
    passed, blocked = pn.gate([p], fort(), Memory())
    assert not passed and blocked[0][1] == "strategist_no_cheats", blocked
    assert "by" not in p.action                            # the action sent is never changed
    passed, blocked = pn.gate([P({"type": "call_migrants"}, rule="recovery")], fort(), Memory())
    assert passed and not blocked


# --- bridge_no_citizen ---

@test("bridge_no_citizen: a pull moving a bridge with a citizen beside it is blocked")
def _():
    s = fort()
    s["units"] = [{"id": 600, "pos": {"x": 101, "y": 98, "z": 150}}]
    why = pn.bridge_no_citizen({"type": "pull_gate", "lever_id": 110}, s, Memory())
    assert why and "beside" in why, why
    s = fort()
    s["entrances"]["entrances"][0]["outer"][0]["own_near"] = True     # a report's own flag
    assert pn.bridge_no_citizen({"type": "pull_gate", "lever_id": 110}, s, Memory())


@test("bridge_no_citizen: nobody near, another lever, or no bridge position: passes")
def _():
    s = fort()
    s["units"] = [{"id": 600, "pos": {"x": 110, "y": 98, "z": 150}}]
    assert pn.bridge_no_citizen({"type": "pull_gate", "lever_id": 110}, s, Memory()) is None
    s["units"] = [{"id": 600, "pos": {"x": 100, "y": 98, "z": 150}}]
    assert pn.bridge_no_citizen({"type": "pull_gate", "lever_id": 187}, s, Memory()) is None   # a hatch
    del s["entrances"]["entrances"][0]["outer"][0]["x"]
    assert pn.bridge_no_citizen({"type": "pull_gate", "lever_id": 110}, s, Memory()) is None


# --- the gate and its step ---

@test("gate: names the first predicate, passes the rest in order, a raising predicate passes")
def _():
    ok1, bad, ok2 = P({"type": "work_order"}), P({"type": "squad_trim", "count": 4}), P({"type": "tool"})
    passed, blocked = pn.gate([ok1, bad, ok2], fort(), Memory())
    assert passed == [ok1, ok2] and blocked[0][0] is bad and blocked[0][1] == "guard_in_every_fort"
    saved = list(pn.NEVER)
    try:
        def boom(a, s, m):
            raise ValueError("x")
        pn.NEVER.insert(0, ("boom", boom))
        errs = []
        passed, blocked = pn.gate([ok1], fort(), Memory(), errs)
        assert passed == [ok1] and errs and errs[0].startswith("boom")
    finally:
        pn.NEVER[:] = saved


@test("never_step: blocked said once, journaled (never_blocked), added to held")
def _():
    said, journ = [], []
    bad = P({"type": "squad_orders", "squad_id": 1, "kill": [501]}, rule="squad_attack")
    good = P({"type": "work_order"})
    passed, held = pn.never_step([bad, good], ["x: waits"], fort(), Memory(), "A", said.append, journ.append)
    assert passed == [good]
    assert held[0] == "x: waits" and "never_kill_citizen" in held[1]
    assert len([x for x in said if "never_kill_citizen" in x]) == 1
    assert journ[0]["kind"] == "never_blocked" and journ[0]["never"] == "never_kill_citizen"
    assert journ[0]["rule"] == "squad_attack" and journ[0]["action"]["kill"] == [501]


@test("never_step: the gate failing whole lets the actions go as selected")
def _():
    saved = pn.gate
    try:
        pn.gate = lambda *a, **k: 1 / 0
        a = [P({"type": "work_order"})]
        passed, held = pn.never_step(a, [], fort(), Memory(), "A", lambda *_: None, None)
        assert passed is a
    finally:
        pn.gate = saved


@test("overseer_cycle: never_step sits between select() and the dispatch loop, on the strategist's too")
def _():
    src = (ROOT / "brain" / "overseer_cycle.py").read_text(encoding="utf-8")
    i_strat = src.index('cycle_step(memory, state, "strategist"')
    i_sel = src.index('cycle_step(memory, state, "select"')
    i_gate = src.index("never_step(allowed, held, state, memory, key, say, journal)")
    i_loop = src.index("for p in allowed:")
    i_act = src.index("r = bridge.act(floor_action(")
    assert i_strat < i_sel < i_gate < i_loop < i_act


if __name__ == "__main__":
    finish()
