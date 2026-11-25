"""planner_guards: the cycle's own guards (0.105.48, K6; audits A9, A12).

- guard_fail / guard_ok / guard_lines: a step of the cycle that failed
  (select's limits for one proposal, one of record()'s hooks, a pre-plan step
  in overseer.one_cycle, the strategist's review) is counted in
  memory.guard_fails, cycles in a row, and said each cycle as a
  "rule <step> failed" note, which the health check's standing lines track
  (health_check.FAIL_NOTE), until the step runs again.
- unknown_filter: a rule that plans on a report section that failed this
  cycle (normalize gave it the empty default) is held: an unread `stocks` is
  not an empty fort (A12: "gather 83 of the 83 shrubs" in a siege).
- outdoor_filter: no work outside (gathering, woodcutting, fishing, hunting,
  pastures, surface building, traps at the way in, outside farm plots) while
  a threat can reach the dwarves or the alarm is up, or when the threats
  couldn't be read. EMERGENCY rules are never held by it.
- meal_glut_filter: no meal cooked, by any rule, while the prepared meals
  are `kitchen_ban_meals_factor` times their target already (D, 22 Nov:
  2,532 servings for 17 dwarves, 150 a dwarf, from meal_variety's biscuits
  and stress_care's lavish meals, none capped; the stock rotted in its
  barrels, 10-25 items at a time, and the rot's miasma beside the kitchen
  left 14 of 17 dwarves disgusted). needs_meal's lavish order is kept: it
  weighs the good meals (worth over 20) and has its own ceiling (0.105.47,
  I7b: plain meals never stand in for a good one).
"""

from __future__ import annotations

from planner_core import EMERGENCY, Proposal, _d, abs_tick, reachable_threats  # noqa: F401

__all__ = ["guard_fail", "guard_ok", "guard_lines", "GUARD_KEEP", "SECTION_NEEDS", "unknown_filter",
           "OUTDOOR_TYPES", "OUTDOOR_LABORS", "is_outdoor", "outdoor_danger", "outdoor_filter",
           "MEAL_ORDER_RECIPES", "meal_glut_filter"]

GUARD_KEEP = 200            # cycles a failing step is counted (the count stops growing there)


def guard_fail(memory, name: str, e: BaseException, now: int | None) -> None:
    """A step of the cycle failed: counted once a cycle (several failures of
    one step in a cycle count once), with the error's words."""
    if memory is None:
        return
    if not isinstance(getattr(memory, "guard_fails", None), dict):
        memory.guard_fails = {}
    prev = _d(memory.guard_fails.get(name))
    n = int(prev.get("n") or 0)
    if prev.get("tick") != now or not n:
        n = min(GUARD_KEEP, n + 1)
    memory.guard_fails[name] = {"n": n, "tick": now, "why": f"{type(e).__name__}: {str(e)[:120]}"}


def guard_ok(memory, name: str) -> None:
    """The step ran: its count is cleared."""
    if memory is not None and isinstance(getattr(memory, "guard_fails", None), dict):
        memory.guard_fails.pop(name, None)


def guard_lines(memory) -> list[str]:
    """The failing steps as notes ("rule <step> failed ...": the health
    check's standing lines)."""
    out = []
    for name, v in sorted(_d(getattr(memory, "guard_fails", None)).items()):
        v = _d(v)
        n = int(v.get("n") or 1)
        out.append(f"rule {name} failed ({str(v.get('why') or '?')[:120]}); the cycle went on without it "
                   f"({n} cycle(s) in a row)")
    return out


# --- unread sections ----------------------------------------------------------

# rule -> the report sections it plans on that plan() doesn't check for it
SECTION_NEEDS = {
    "gather": ("stocks",),            # food a dwarf
    "gather_trim": ("stocks",),
    "good_cooks": ("stocks",),        # meals a dwarf
    "recreation": ("others_on_map",),     # sent out to play in a siege
    "soldier_swap": ("others_on_map",),   # a soldier out of his squad in a siege
    "ore": ("military",),             # "0 bars of weapon-grade metal"
    "smelt": ("military",),
}
# (rule, action field, value) -> sections: the gatherers the gather rule asks for
SECTION_NEEDS_ACTION = {("labor", "job", "gathering"): ("stocks",)}


def _needs(p: Proposal) -> tuple:
    a = _d(p.action)
    need = SECTION_NEEDS.get(p.rule, ())
    for (rule, k, v), secs in SECTION_NEEDS_ACTION.items():
        if p.rule == rule and a.get(k) == v:
            need = need + secs
    return need


def unknown_filter(s: dict, proposals: list, notes: list) -> list:
    """Proposals planned on a report section that failed this cycle: held
    (unknown is not zero). A release (let out, called back) is never held."""
    errors = _d(s.get("_errors"))
    if not errors:
        return proposals
    kept, held = [], {}
    for p in proposals:
        bad = [x for x in _needs(p) if x in errors]
        if bad and p.rule not in EMERGENCY and not _d(p.action).get("release") and not _d(p.action).get("stop"):
            held.setdefault(", ".join(bad), []).append(p.rule)
            continue
        kept.append(p)
    for secs, rules in held.items():
        notes.append(f"{', '.join(sorted(set(rules)))} wait(s): the report's {secs} couldn't be read this cycle "
                     "(unknown is not none)")
    return kept


# --- meals past any use -------------------------------------------------------

MEAL_ORDER_RECIPES = {"prepare_easy_meal", "prepare_fine_meal", "prepare_lavish_meal"}
MEAL_GLUT_KEEP = {"needs_meal"}      # good meals short: its own ceiling (meals_hard_max_pd) and lavish_due


def meal_glut_filter(s: dict, cfg: dict, proposals: list, notes: list) -> list:
    """Meal orders held while the prepared meals are `kitchen_ban_meals_factor`
    times their target (`meals_per_dwarf` a citizen): more only rots. An
    unread stock or no citizens holds nothing; needs_meal's order (good meals
    short, by planner_society.lavish_due) is never held."""
    st = _d(s.get("stocks"))
    have = st.get("prepared_meals")
    citizens = _d(s.get("dwarves")).get("total")
    if isinstance(have, bool) or not isinstance(have, (int, float)):
        return proposals
    if isinstance(citizens, bool) or not isinstance(citizens, (int, float)) or citizens <= 0:
        return proposals
    cap = citizens * float(cfg.get("meals_per_dwarf", 8)) * float(cfg.get("kitchen_ban_meals_factor", 3))
    if have < cap:
        return proposals
    kept, held = [], []
    for p in proposals:
        a = _d(p.action)
        if (a.get("type") == "work_order" and a.get("recipe") in MEAL_ORDER_RECIPES
                and p.rule not in MEAL_GLUT_KEEP):
            held.append(p.rule)
            continue
        kept.append(p)
    if held:
        notes.append(f"{', '.join(sorted(set(held)))}: no meals cooked: {int(have)} servings for {int(citizens)} "
                     f"citizen(s), over {int(cap)} already (more would only rot)")
    return kept


# --- outdoor work in danger -----------------------------------------------------

OUTDOOR_TYPES = {"gather_plants", "make_pasture", "pasture", "place_surface", "place_keep", "place_hall",
                 "build_wings", "place_garden_court", "build_crossing", "fruit_zone", "place_traps"}
OUTDOOR_LABORS = {"gathering", "fishing", "woodcutting", "hunting", "GATHER_PLANTS", "FISH", "CUTWOOD", "HUNT",
                  "plant_gathering"}


def is_outdoor(p: Proposal) -> bool:
    a = _d(p.action)
    t = a.get("type")
    if t == "fruit_zone" and a.get("pause") is True:
        return False                     # (item6) pausing the zones keeps the gatherers in
    if t in OUTDOOR_TYPES:
        return True
    if t == "keep_grove" and not a.get("guard"):
        return True
    if t == "farm_plots" and a.get("outside"):
        return True
    if t == "assign_labor" and a.get("job") in OUTDOOR_LABORS and int(a.get("count") or 0) > 0:
        return True
    if t == "hunters" and not a.get("stop") and int(a.get("count") or 0) > 0:
        return True
    if t == "tool" and a.get("name") == "autochop" and a.get("enabled"):
        return True
    return False


def outdoor_danger(s: dict, memory, traits: dict, cfg: dict) -> str:
    """Why no one goes outside now ("" when they may): a threat that can reach
    the dwarves, the alarm up, or the threats unread."""
    errors = _d(s.get("_errors"))
    if "others_on_map" in errors:
        return "the threats couldn't be read this cycle"
    if s.get("civ_alert") is True or ("civ_alert" in errors and getattr(memory, "ai_alert_raised", False)):
        return "the alarm is up"
    try:
        n = len(reachable_threats(s, traits, cfg))
    except Exception:  # noqa: BLE001  (unknown: kept in)
        return "the threats couldn't be judged this cycle"
    return f"{n} threat(s) can reach the dwarves" if n else ""


def outdoor_filter(s: dict, memory, traits: dict, cfg: dict, proposals: list, notes: list) -> list:
    """No outdoor work while danger is about (EMERGENCY rules excepted)."""
    out = [p for p in proposals if is_outdoor(p) and p.rule not in EMERGENCY]
    if not out:
        return proposals
    why = outdoor_danger(s, memory, traits, cfg)
    if not why:
        return proposals
    notes.append(f"{why}: no work outside ({', '.join(sorted({p.rule for p in out}))} wait)")
    return [p for p in proposals if p not in out]
