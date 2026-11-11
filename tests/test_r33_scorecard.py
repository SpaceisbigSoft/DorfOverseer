"""r33 scorecard group: the sliders' signatures (sliders/greed.md, growth.md,
caution.md, industry.md, moods.md, spacing.md) and the scorecard lines that
count them.

    python tests/test_r33_scorecard.py
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import quirks  # noqa: E402
import scorecard  # noqa: E402
import weights  # noqa: E402
from planner import Memory, plan  # noqa: E402
from planner_core import PLANNER_CONFIG, Proposal  # noqa: E402
from planner_growth import fort_strain, strain_unhappy_lines, _pop_cap_rule  # noqa: E402
from planner_industry import _gems_rule  # noqa: E402
from planner_trade import keeps_treasures  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(PLANNER_CONFIG)


def by_rule(ps, rule):
    return [p for p in ps if p.rule == rule]


# ------------------------------------------------------------------ Growth

def strained(pop=50, unhappy=0, traits=None, drink=None, meals=None):
    s = copy.deepcopy(BASE)
    s["settings"]["traits"] = dict(traits or {})
    s["dwarves"]["total"] = pop
    s["dwarves"]["stress"] = {"content": pop - unhappy, "unhappy": unhappy}
    s["stocks"]["drink"] = pop * 10 if drink is None else drink
    s["stocks"]["prepared_meals"] = pop * 10 if meals is None else meals
    return s


@test("Growth: no strain hold while the fort is young (day 17: no meals yet, cap held at 7)")
def _():
    young = strained(pop=7, meals=0)          # (0.105.33 fix) drink short still holds: test_r33_fix_people
    young["farms"] = {}
    assert fort_strain(young, CFG) == [], fort_strain(young, CFG)
    assert fort_strain(young, CFG, held=True) == []
    # an established fort short of meals is still held: survival is not character
    big = strained(pop=50, meals=0)
    assert any("meals" in x for x in fort_strain(big, CFG)), fort_strain(big, CFG)


@test("Growth: the unhappy hold leans with Growth (Merchant +60 holds at 30%, Hermit -60 at 13%)")
def _():
    assert strain_unhappy_lines({}, CFG, {}) == (20, 12)
    hi, hi_ok = strain_unhappy_lines({}, CFG, {"growth": 60})
    lo, lo_ok = strain_unhappy_lines({}, CFG, {"growth": -60})
    assert 30 <= hi <= 31 and 18 <= hi_ok <= 19 and 13 <= lo <= 14 and 7.5 <= lo_ok <= 8.5, (hi, hi_ok, lo, lo_ok)
    assert strain_unhappy_lines({}, CFG, {"growth": 400}) == (40, 24)        # x2 at most
    # 25% unhappy (12 of 50): neutral holds, Merchant doesn't, Hermit does; read from the report's traits too
    assert fort_strain(strained(unhappy=12), CFG)
    assert not fort_strain(strained(unhappy=12, traits={"growth": 60}), CFG)
    assert fort_strain(strained(unhappy=12, traits={"growth": 60}), CFG, traits={"growth": 0})
    assert fort_strain(strained(unhappy=8, traits={"growth": -60}), CFG)       # 16%
    assert not fort_strain(strained(unhappy=8), CFG)
    # let go: held, the Merchant at 20% (over neutral's 12%) is still held until 18%
    assert fort_strain(strained(unhappy=10, traits={"growth": 60}), CFG, held=True)
    assert not fort_strain(strained(unhappy=8, traits={"growth": 60}), CFG, held=True)
    # drink stays unscaled
    assert any("drink" in x for x in fort_strain(strained(drink=10, traits={"growth": 60}), CFG))


@test("Growth: the cap rule holds a strained neutral fort and lets a Merchant city grow at 25% unhappy")
def _():
    for traits, held in (({}, True), ({"growth": 60}, False)):
        s = strained(pop=50, unhappy=12, traits=traits)
        s["society"]["pop_cap"], s["society"]["strict_pop_cap"] = 30, 40
        props, notes = [], []
        _pop_cap_rule(s, Memory(), CFG, 50, props, notes)
        p = by_rule(props, "pop_cap")
        assert p and (("strained" in p[0].reason) == held), (traits, [x.reason for x in p])


# ------------------------------------------------------------------ Greed

def gem_fort(traits):
    s = copy.deepcopy(BASE)
    s["settings"]["traits"] = dict(traits)
    s.setdefault("buildings", {}).setdefault("workshops", {})["Jewelers"] = 1
    s["trade"] = {"depot": True, "caravans": [], "goods": 40,
                  "cut_gem": {"n": 30, "total": 30, "token": "INORGANIC:PINK JADE"}}
    s["orders"] = []
    return s


@test("Greed: keeps_treasures from +30 (the Hermit hold at 40 counts), a trading fort keeps them too")
def _():
    assert keeps_treasures({"greed": 30}) and keeps_treasures({"greed": 40}) and not keeps_treasures({"greed": 20})
    s = copy.deepcopy(BASE)
    s["trade"] = {"depot": True, "caravans": [{"civ": "the Mountainhomes", "state": "Approaching"}], "goods": 50,
                  "at_depot": 0}
    s["settings"]["traits"] = {"trade": 120, "greed": 80}         # the Merchant city
    t = by_rule(plan(s, Memory())[0], "trade")
    assert t and t[0].action.get("keep_treasures") is True, t


@test("Greed: a grasping fort hoards its cut gems (no encrusting); a generous one sets 10 at a time")
def _():
    out, notes = [], []
    _gems_rule(gem_fort({"greed": 40}), CFG, out, notes=notes)
    assert not by_rule(out, "encrust") and any("hoards its gems" in n for n in notes), (out, notes)
    out = []
    _gems_rule(gem_fort({}), CFG, out)
    assert by_rule(out, "encrust")[0].action["amount"] == 5
    out = []
    _gems_rule(gem_fort({"greed": -60}), CFG, out)
    assert by_rule(out, "encrust")[0].action["amount"] == 10
    # Gem-mad (memory) hoards too, whatever the slider
    m = Memory()
    m.culture = {"quirks": {"gem_mad": {"year": 252}}}
    out = []
    _gems_rule(gem_fort({}), CFG, out, memory=m)
    assert not by_rule(out, "encrust"), out
    # plan() (traits from the report): the Hermit hold's gems stay
    s = gem_fort({"greed": 40})
    assert not by_rule(plan(s, Memory())[0], "encrust")


@test("Greed: Gem-mad's jeweller and 100-gem branches need Greed above 0 (B at -60 no longer earns it)")
def _():
    q = quirks.data()["quirks"]["gem_mad"]
    for f in ({"jewelers": 1, "gems": 60}, {"gems": 120}):
        assert quirks._test(q["earn"], {"greed": 1}, f)[0], f
        assert not quirks._test(q["earn"], {"greed": 0}, f)[0], f     # (0.105.33 fix) neutral forts encrust
        assert not quirks._test(q["earn"], {"greed": -60}, f)[0], f
    assert quirks._test(q["earn"], {"greed": 80}, {"cut_gems": 60})[0]


# ------------------------------------------------------------------ Caution

@test("Caution: the second stairwell wins in the War-hold and Hermit hold, not in the Deep mine or neutral forts")
def _():
    P = {"A": {"militarism": 150, "fortification": 120, "caution": 60, "engineering": 60, "justice": 80,
               "deference": 40, "outsiders": -80, "grandeur": -40, "welfare": -40, "piety": -30, "spacing": -60,
               "mining": 40},
         "D": {"outsiders": -150, "trade": -100, "growth": -60, "caution": 60, "surface": -60, "fortification": 100,
               "deference": -60, "greed": 40, "stockpile": 60},
         "E": {"mining": 150, "verticality": 120, "surface": -100, "engineering": 60, "industriousness": 60,
               "caution": -40, "spacing": -30, "agriculture": -20},
         "N": {}}

    def top(t):
        r = weights.score_area("stairwells", t)
        r = r if isinstance(r, list) else r.get("ranked", r)
        return max(r, key=lambda x: x["score"])["id"]
    assert {k: top(t) for k, t in P.items()} == {"A": "two", "D": "two", "E": "one", "N": "one"}


# ------------------------------------------------------------------ the scorecard

def dec(t, result=None, reason="", year=252, tick=1000, **a):
    return {"kind": "decision", "date": {"year": year, "tick": tick}, "reason": reason,
            "action": {"type": t, **a}, "result": {"ok": True, **(result or {})}}


def rep(topic, typ, text=""):
    return {"kind": "event", "event": {"kind": "report", "topic": topic, "type": typ, "text": text,
                                       "year": 252, "tick": 500}}


NOW = {"year": 253, "tick": 0}


@test("scorecard: alarms count raises only; second stairwells; polish runs; MADE_ARTIFACT only")
def _():
    j = scorecard.journal_counts([dec("civ_alert", {"on": True}, on=True), dec("civ_alert", {"on": False}, on=False),
                                  dec("dig_stairwell"), dec("polish"), dec("polish"),
                                  rep("mood", "STRANGE_MOOD"), rep("mood", "FEY_MOOD"),
                                  rep("artifact_made", "MADE_ARTIFACT"),
                                  rep("artifact_made", "NAMED_ARTIFACT", "has bestowed the name X upon a shield")],
                                 NOW)
    m = scorecard.measures(copy.deepcopy(BASE), j)
    assert m["alerts"] == 1 and m["stairwells_dug"] == 1 and m["polish_runs"] == 2, m
    h = scorecard.health(copy.deepcopy(BASE), j)
    assert h["artifacts"] == 1 and h["failed_moods"] == 1, h


@test("scorecard Greed: gems set into goods, gems kept of those cut, treasures held back")
def _():
    j = scorecard.journal_counts([dec("work_order", {"amount": 4}, recipe="encrust_goods", amount=4),
                                  dec("work_order", {"amount": 5}, recipe="encrust_goods", amount=5),
                                  dec("work_order", {"amount": 10}, recipe="cut_gems", amount=10),
                                  dec("work_order", {"amount": 10}, recipe="cut_gems", amount=10),
                                  dec("bring_goods", {"value": 10}, keep_treasures=True), dec("bring_goods")], NOW)
    s = copy.deepcopy(BASE)
    s["stocks"]["cut_gems"], s["stocks"]["rough_gems"] = 6, 5
    m = scorecard.measures(s, j)
    assert m["gems_set"] == 9 and m["treasures_kept"] == 1, m
    assert m["gems_kept_pct"] == round(100 * 11 / 25, 1), m


@test("scorecard Growth: newcomers welcome, % of the last year's days (cap over the population)")
def _():
    D = scorecard.TICKS_PER_DAY
    caps = [dec("set_population_cap", {"cap": 100}, year=252, tick=0, cap=100),
            dec("set_population_cap", {"cap": 40}, "the fort is strained: no newcomers for now",
                year=252, tick=200 * D, cap=40)]
    base = 252 * 336
    tl = [(base + d, 40) for d in range(336)]
    j = scorecard.journal_counts(caps, NOW, tl)
    m = scorecard.measures(copy.deepcopy(BASE), j)
    assert m["welcome_pct"] == round(100 * 200 / 336, 1), m["welcome_pct"]
    # rows of another run (before this run's first decision) are left out; no timeline: no data
    j2 = scorecard.journal_counts(caps, NOW, [(base - 10, 1)] + tl)
    assert scorecard.measures(copy.deepcopy(BASE), j2)["welcome_pct"] == m["welcome_pct"]
    assert scorecard.measures(copy.deepcopy(BASE), scorecard.journal_counts(caps, NOW))["welcome_pct"] is None


@test("scorecard Industry: idle_free of the adults not in squads, needs.social.idle before it, idle_adults last")
def _():
    j = scorecard.journal_counts([], NOW)
    s = copy.deepcopy(BASE)
    s["dwarves"].update({"adults": 60, "in_squads": 20, "idle_adults": 30})
    s.setdefault("needs", {})["social"] = {"idle": 8}
    assert scorecard.measures(s, j)["idle_pct"] == 20.0
    s["dwarves"]["idle_free"] = 4
    assert scorecard.measures(s, j)["idle_pct"] == 10.0 and scorecard.health(s, j)["idle_pct"] == 10.0
    del s["dwarves"]["idle_free"]
    s["needs"].pop("social")
    assert scorecard.measures(s, j)["idle_pct"] == 75.0


@test("scorecard Spacing: new corridor a level (new_corridor, corridor before it), tiles a bedroom")
def _():
    j = scorecard.journal_counts([
        dec("start_project", {"kind": "bedrooms", "tiles": 100, "corridor": 12, "new_corridor": 4,
                              "summary": {"rooms": 10}}, kind="bedrooms", rooms=10),
        dec("start_project", {"kind": "storage", "tiles": 150, "corridor": 8}, kind="storage"),
        dec("start_project", {"kind": "bedrooms", "tiles": 60, "corridor": 2}, kind="bedrooms", rooms=6)], NOW)
    m = scorecard.measures(copy.deepcopy(BASE), j)
    assert m["corridor_mean"] == round((4 + 8 + 2) / 3, 1) and m["bedroom_tiles"] == 10.0, m
    lines = {k for _, _, k, _, _ in scorecard.LINES}
    for k in ("-gems_set", "gems_kept_pct", "treasures_kept", "welcome_pct", "stairwells_dug", "polish_runs",
              "-corridor_mean", "-bedroom_tiles"):
        assert k in lines, k
    assert "wealth_pd" not in lines and "gems" not in lines and "-level_tiles" not in lines


if __name__ == "__main__":
    finish()
