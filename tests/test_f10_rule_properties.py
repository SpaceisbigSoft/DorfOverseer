"""(F1b) Rule-set properties on the real reports (tests/fixtures/real).

The planner end to end (normalize, note_cycle, plan, select, record) on each
recorded fort report, over several cycles a game day apart:

(a) answered ok every cycle: no plan sends an inverse pair on one object
    (open and close the trade, raise and lower the alarm, fill and trim one
    squad, a burrow set and released, one lever pulled twice); the pairs are
    the INVERSE table below, each action read as (object, direction).
(b) the same failure answered for every action, ten cycles: no action sent
    more than three times (MAX_TRIES). Today a refused action is retried
    about every other cycle (4 times in 10 in every fixture), so (b) is an
    expected failure (xfail, below) until the attempt ledger (another F
    group) lands; then it passes and this test says so (XPASS) to be made
    strict.

The fixtures predate 0.105: refresh them from the six forts with
tools/refresh_real_fixtures.py (on the PC) each release.

    python tests/test_f10_rule_properties.py
"""

from __future__ import annotations

import collections
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish, skip  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from digest import normalize  # noqa: E402
from planner import Memory, Proposal, note_cycle, plan, record, select  # noqa: E402
from planner_core_base import TICKS_PER_DAY, TICKS_PER_YEAR  # noqa: E402

REAL = ROOT / "tests" / "fixtures" / "real"
CYCLES = 10
MAX_TRIES = 3
STEP = TICKS_PER_DAY        # a game day passes in about one planner cycle (gap F2)
FAIL_REPLY = {"ok": False, "error": "refused (test: the same failure every time)"}


def _on(key: str, default=True):
    return lambda a: bool(a.get(key, default))


def _off(key: str):
    return lambda a: not a.get(key)


# action type -> (object of the action, direction): two actions of one plan on
# the same object in opposite directions are an inverse pair. A direction of
# None is a toggle (pull_gate): the same object twice in one plan is a pair.
INVERSE: dict[str, tuple] = {
    "civ_alert":              (lambda a: ("alarm",), _on("on")),
    "tool":                   (lambda a: ("tool", a.get("name")), _on("enabled")),
    "weather_burrow":         (lambda a: ("weather_burrow",), _on("on")),
    "hospital_burrow":        (lambda a: ("hospital_burrow",), _off("release")),
    "calm_burrow":            (lambda a: ("calm_burrow",), _off("release")),
    "fire_guard":             (lambda a: ("fire_guard",), _off("lift")),
    "kitchen_cheap":          (lambda a: ("kitchen_cheap",), _on("ban")),
    "kitchen_fat":            (lambda a: ("kitchen_fat",), _on("ban")),
    "open_trade":             (lambda a: ("trade",), lambda a: True),
    "close_trade":            (lambda a: ("trade",), lambda a: False),
    "open_gates":             (lambda a: ("gates",), lambda a: True),
    "close_threatened_gates": (lambda a: ("gates",), lambda a: False),
    "pull_gate":              (lambda a: ("lever", a.get("lever_id")), None),
    "seal_cavern":            (lambda a: ("cavern", a.get("layer")), lambda a: bool(a.get("open"))),
    "squad_fill":             (lambda a: ("squad", a.get("squad_id")), lambda a: True),
    "squad_trim":             (lambda a: ("squad", a.get("squad_id")), lambda a: False),
    "squad_swap":             (lambda a: ("squad member", a.get("unit_id")), lambda a: True),
    "squad_release":          (lambda a: ("squad member", a.get("unit_id")), lambda a: False),
    "squad_orders":           (lambda a: ("squad orders", a.get("squad_id")), lambda a: not a.get("clear")),
    "add_haulers":            (lambda a: ("haulers",), lambda a: True),
    "relieve_haulers":        (lambda a: ("haulers",), lambda a: False),
    "build_crossing":         (lambda a: ("crossing", a.get("x"), a.get("y"), a.get("z")), lambda a: True),
    "start_project":          (lambda a: ("project", a.get("kind")), lambda a: True),
}


def inverse_pairs(actions: list[dict]) -> list[tuple[dict, dict]]:
    """The inverse pairs among one plan's actions (by the INVERSE table)."""
    seen: dict[tuple, dict] = {}
    pairs = []
    for a in actions:
        e = INVERSE.get(str(a.get("type")))
        if not e:
            continue
        obj, way = e
        try:
            o = repr(obj(a))
            d = None if way is None else way(a)
        except Exception:  # noqa: BLE001  an odd action is no pair
            continue
        if o in seen:
            b, bd = seen[o]
            if way is None or bd != d:
                pairs.append((b, a))
            continue
        seen[o] = (a, d)
    return pairs


def action_key(a: dict) -> str:
    return json.dumps(a, sort_keys=True, default=str)


def fixtures() -> list[Path]:
    fs = sorted(REAL.glob("*.json"))
    if not fs:
        skip(f"no real report in {REAL}")
    return fs


def cycle_state(s0: dict, i: int) -> dict:
    s = copy.deepcopy(s0)
    t = int(s0["date"]["year"]) * TICKS_PER_YEAR + int(s0["date"]["tick"]) + i * STEP
    s["date"]["year"], s["date"]["tick"] = divmod(t, TICKS_PER_YEAR)
    normalize(s)
    return s


def run_cycles(s0: dict, reply, cycles: int = CYCLES):
    """[(proposals, allowed)] of each cycle, every allowed action answered reply(p)."""
    m = Memory()
    out = []
    for i in range(cycles):
        s = cycle_state(s0, i)
        note_cycle(s, m)
        props, _ = plan(s, m)
        allowed, _ = select(props, s, m)
        out.append((props, allowed))
        record([(p, dict(reply(p))) for p in allowed], s, m)
    return out


# --- the checker itself --------------------------------------------------------------

@test("inverse pairs: the table finds open+close, on+off, fill+trim, a lever twice; not two unlike objects")
def _():
    assert inverse_pairs([{"type": "open_trade"}, {"type": "close_trade"}])
    assert inverse_pairs([{"type": "civ_alert", "on": True}, {"type": "civ_alert", "on": False}])
    assert inverse_pairs([{"type": "squad_fill", "squad_id": 3, "count": 2}, {"type": "squad_trim", "squad_id": 3}])
    assert not inverse_pairs([{"type": "squad_fill", "squad_id": 3}, {"type": "squad_trim", "squad_id": 4}])
    assert inverse_pairs([{"type": "pull_gate", "lever_id": 9}, {"type": "pull_gate", "lever_id": 9}])
    assert not inverse_pairs([{"type": "pull_gate", "lever_id": 9}, {"type": "pull_gate", "lever_id": 8}])
    assert inverse_pairs([{"type": "hospital_burrow", "max": 5}, {"type": "hospital_burrow", "release": True}])
    assert not inverse_pairs([{"type": "tool", "name": "autochop", "enabled": True},
                              {"type": "tool", "name": "nestboxes", "enabled": False}])
    assert not inverse_pairs([{"type": "work_order", "recipe": "x"}, {"type": "work_order", "recipe": "x"}])
    assert inverse_pairs([{"type": "start_project", "kind": "hospital"},
                          {"type": "start_project", "kind": "hospital"}]) == []   # same way twice: no pair


@test("real fixtures: there are some, each a report the planner reads (date, dwarves)")
def _():
    fs = fixtures()
    for f in fs:
        s = json.loads(f.read_text(encoding="utf-8"))
        assert isinstance(s.get("date"), dict) and "tick" in s["date"] and "year" in s["date"], f.name
        assert "dwarves" in s, f.name


# --- (a) no inverse pair on one object in one plan --------------------------------------

@test("(a) everything answered ok, planned again each day for 10 cycles: no plan sends an inverse pair")
def _():
    bad = []
    for f in fixtures():
        s0 = json.loads(f.read_text(encoding="utf-8"))
        for i, (props, allowed) in enumerate(run_cycles(s0, lambda p: {"ok": True})):
            for a, b in inverse_pairs([p.action for p in allowed]):
                bad.append(f"{f.name} cycle {i + 1}: {action_key(a)[:100]} / {action_key(b)[:100]}")
    assert not bad, "\n".join(bad[:20])


@test("(a) nor does any plan propose one (before select's limits)")
def _():
    bad = []
    for f in fixtures():
        s0 = json.loads(f.read_text(encoding="utf-8"))
        for i, (props, _) in enumerate(run_cycles(s0, lambda p: {"ok": True}, cycles=3)):
            for a, b in inverse_pairs([p.action for p in props]):
                bad.append(f"{f.name} cycle {i + 1}: {action_key(a)[:100]} / {action_key(b)[:100]}")
    assert not bad, "\n".join(bad[:20])


# --- (b) the same failure ten times: no action sent more than three times ---------------

def tries_over_cap() -> list[str]:
    over = []
    for f in fixtures():
        s0 = json.loads(f.read_text(encoding="utf-8"))
        sent: collections.Counter = collections.Counter()
        for _, allowed in run_cycles(s0, lambda p: FAIL_REPLY):
            sent.update(action_key(p.action) for p in allowed)
        over += [f"{f.name}: {n}x {k[:110]}" for k, n in sent.most_common() if n > MAX_TRIES]
    return over


@test("(b) the same failure for every action, 10 cycles: no action sent more than 3 times (xfail: attempt ledger)")
def _():
    over = tries_over_cap()
    if over:
        # xfail: the planner has no attempt ledger yet (a refusal starts no cooldown
        # of its own, gap F2 "failure memory"); the ledger is another F group's item.
        # Do not change planner code to pass this here.
        skip(f"xfail (expected until the attempt ledger lands): {len(over)} actions over {MAX_TRIES} "
             f"tries, e.g. {over[0]}")
    # XPASS: the ledger works; make this test strict (drop the skip above)


@test("(b) the run itself: the failure is recorded (the rules see a refusal, nothing raises)")
def _():
    f = fixtures()[0]
    s0 = json.loads(f.read_text(encoding="utf-8"))
    out = run_cycles(s0, lambda p: FAIL_REPLY, cycles=2)
    assert len(out) == 2 and all(isinstance(p, Proposal) for props, _ in out for p in props)


if __name__ == "__main__":
    finish()
