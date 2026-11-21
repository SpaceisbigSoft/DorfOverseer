"""(r4 k1, audit A7 B1/B2) The strategist's holds judged by the rule's class,
its raises by the kinds of action the rule takes: never a survival or
defence rule held; never a kill/squad order, expulsion, gate, lever, hatch,
trade, butcher, conviction, opened cavern seal, lure, kill zone or hunt
raised, whatever the rule's name or when it was added.

    python tests/test_r4_k1.py
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

import hold_classes as H  # noqa: E402
import strategist as S  # noqa: E402
from backends import Reply  # noqa: E402
from planner import Memory, Proposal, TICKS_PER_DAY, abs_tick, select  # noqa: E402
from tokens import TokenBank  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
REAL = json.loads((ROOT / "tests" / "fixtures" / "real" / "enxah-0.104.52-y73-winter.json").read_text(encoding="utf-8"))
RECIPES, TOOLS = {"brew_drink"}, {"autochop"}


def ask(acts, shown=None, **kw):
    return S.check_answer(json.dumps({"note": "x", "actions": acts}), RECIPES, TOOLS, set(), shown=shown, **kw)


def hold(rule, days=84):
    return ask([{"type": "hold", "rule": rule, "days": days, "why": "x"}], shown={rule})


def raise_(rule, **kw):
    return ask([{"type": "raise", "rule": rule, "why": "x"}], shown={rule}, **kw)


# --- B1: holds by class ------------------------------------------------------------

@test("B1: no survival or defence rule in hold_classes can be held (walks RULE_SETS)")
def _():
    bad = []
    for cls in (H.SURVIVAL, H.DEFENCE):
        for rule in sorted(H.RULE_SETS[cls]):
            if rule == "build":
                continue
            a = hold(rule)
            if a.steer or not any("can't be held" in r for r in a.rejected):
                bad.append(rule)
    assert not bad, f"{len(bad)} held: {bad[:20]}"


@test("B1: the audit's accepted holds are refused, with the reason in the rejected list")
def _():
    for rule in ("care_feed", "care_diagnose", "cave_in_dig_out", "join_levels", "second_way", "shelter_supply",
                 "prisoners_water", "well_dig", "syndrome_quarantine", "arms", "train", "squad_make", "traps",
                 "chronic_care", "burial_others", "crafts", "dairy"):
        a = hold(rule)
        assert not a.steer, rule
        assert any(rule in r and "can't be held" in r and ("survival" in r or "defence" in r or "safety" in r)
                   for r in a.rejected), (rule, a.rejected)


@test("B1: an expansion rule can still be held; build two weeks at most; a rule in no class is not held")
def _():
    a = hold("grandeur", 30)
    assert a.steer == [{"type": "hold", "rule": "grandeur", "days": 30, "why": "x"}], a.rejected
    a = hold("build", 84)
    assert a.steer and a.steer[0]["days"] == 14, a.rejected
    a = hold("r4k1_unknown_rule")
    assert not a.steer and "no class" in a.rejected[0], a.rejected


@test("B1: in select, a stored hold of a defence rule (an old save) holds nothing and is dropped")
def _():
    s = json.loads(json.dumps(BASE))
    now = abs_tick(s)
    m = Memory()
    m.steer = {"arms": {"mode": "hold", "until": now + 50 * TICKS_PER_DAY, "why": "old"}}
    allowed, held = select([Proposal("arms", {"type": "work_order", "recipe": "brew_drink", "amount": 1}, "x", 5)],
                           s, m)
    assert not any("held by the strategist" in h for h in held), held
    from planner import note_cycle
    note_cycle(copy.deepcopy(s), m)
    assert "arms" not in m.steer, m.steer


@test("B1: an expansion rule's safe step (a floodgate shut) is never held by a hold of the rule")
def _():
    s = json.loads(json.dumps(BASE))
    now = abs_tick(s)
    m = Memory()
    m.steer = {"waterworks_moat": {"mode": "hold", "until": now + 10 * TICKS_PER_DAY, "why": "x"}}
    shut = Proposal("waterworks_moat", {"type": "water_work", "shut": True}, "leak", 0)
    dig = Proposal("waterworks_moat", {"type": "water_work", "step": "dig"}, "more", 6)
    allowed, held = select([shut, dig], s, m)
    assert shut in allowed, held
    assert dig not in allowed and any("held by the strategist" in h for h in held), held


# --- B2: raises by action kind ------------------------------------------------------

@test("B2: the audit's raisable kill/open/slaughter rules are refused")
def _():
    for rule in ("hunt", "wild_hunt", "caravan_guard", "beast_hunt", "lure_open", "killzone", "contact",
                 "chronic_convict", "herd_cull", "pit_prisoners", "cleanup_units", "gates", "seal_cavern",
                 "trade", "slaughter", "mission", "expel"):
        a = raise_(rule)
        assert not a.steer and any(rule in r and "can't be raised" in r for r in a.rejected), (rule, a.rejected)


@test("B2: every Proposal( in brain/ with a literal kill/gate/lever/trade/butcher/... action can't be raised")
def _():
    import steer_guard as G
    pat = re.compile(r'Proposal\(\s*"([a-z0-9_]+)"\s*,\s*\{\s*"type"\s*:\s*"([a-z_]+)"([^}]*)\}')
    found, bad = 0, []
    for f in sorted((ROOT / "brain").glob("*.py")):
        for rule, kind, rest in pat.findall(f.read_text(encoding="utf-8")):
            if kind == "squad_orders" and '"clear": True' in rest and '"kill"' not in rest:
                continue
            if kind == "hunters" and '"stop": True' in rest:
                continue
            if kind == "seal_cavern" and '"open"' not in rest:
                continue
            if kind not in G.RAISE_NEVER and kind != "seal_cavern":
                continue
            found += 1
            if raise_(rule).steer:
                bad.append(f"{f.name}:{rule}:{kind}")
    assert found > 40, found
    assert not bad, bad


@test("B2: a rule added later is judged by what it does (scan of its source, the review's own proposals)")
def _():
    import steer_guard as G
    src = ('def r(s, proposals):\n'
           '    act = {"type": "hunt_send", "squad_ids": [1]}\n'
           '    proposals.append(Proposal("r4k1_new_hunt", act, "x", 3))\n'
           '    proposals.append(Proposal("r4k1_new_calm", {"type": "calm_burrow"}, "x", 3))\n')
    exact, _ = G.scan_source(src)
    assert exact["r4k1_new_hunt"] and not exact["r4k1_new_calm"], exact
    seen = {"r4k1_novel": [{"type": "open_gates"}], "r4k1_calm": [{"type": "calm_burrow"}],
            "r4k1_recall": [{"type": "squad_orders", "squad_id": 1, "clear": True}]}
    a = raise_("r4k1_novel", seen=seen)
    assert not a.steer and "gates opened" in a.rejected[0], a.rejected
    for ok in ("r4k1_calm", "r4k1_recall"):
        assert raise_(ok, seen=seen).steer, ok
    assert raise_("grandeur").steer and raise_("crafts").steer


@test("B2: in select, a stored raise never skips the cooldown of a kill order, whatever the rule")
def _():
    s = json.loads(json.dumps(BASE))
    now = abs_tick(s)
    m = Memory()
    m.steer = {"r4k1_x": {"mode": "raise", "until": now + 7 * TICKS_PER_DAY, "why": "x"}}
    m.last_fired["r4k1_x"] = now - 1
    p = Proposal("r4k1_x", {"type": "squad_orders", "squad_id": 1, "kill": [5]}, "x", 3)
    allowed, held = select([p], s, m)
    assert p not in allowed and any("cooldown" in h for h in held), (allowed, held)
    q = Proposal("r4k1_x", {"type": "tool", "name": "autochop", "enabled": True}, "x", 3)
    allowed, held = select([q], s, m)
    assert q in allowed, held


# --- said in the review --------------------------------------------------------------

class Fake:
    def __init__(self, text):
        self.text = text

    def ask(self, instr, msg, important=False, effort=None):
        return Reply(text=self.text, input_tokens=1000, output_tokens=200, model="fake")


@test("the review says each refused hold and raise, and journals it")
def _():
    from planner import plan
    from review import maybe_review
    s = copy.deepcopy(REAL)
    s.setdefault("settings", {}).update({"ai_frequency": 0, "ai_effort": 0, "real_day_token_cap": 0})
    m = Memory()
    props, notes = plan(copy.deepcopy(s), m)
    props = [Proposal("hunt", {"type": "hunt_send", "squad_ids": [1], "target_id": 9}, "x", 2)] + props
    c = Fake(json.dumps({"note": "x", "actions": [{"type": "hold", "rule": "arms", "days": 30, "why": "a"},
                                                  {"type": "raise", "rule": "hunt", "why": "b"},
                                                  {"type": "hold", "rule": "grandeur", "days": 5, "why": "c"}]}))
    info = {"recipes": sorted(RECIPES), "tools": sorted(TOOLS), "level_kinds": ["bedrooms"], "stockpiles": [],
            "workshops": []}
    out = maybe_review(s, m, TokenBank(), c, info, notes, proposals=props)
    said = "\n".join(out.say)
    assert "hold: arms keeps the fort safe" in said and "raise: hunt can't be raised" in said, said
    assert "arms" not in m.steer and "hunt" not in m.steer and m.steer.get("grandeur", {}).get("mode") == "hold"
    assert any("arms" in r for r in out.journal["rejected"]), out.journal


finish()
