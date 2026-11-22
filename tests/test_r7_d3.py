"""r7 d3: brain/planner_core.py split into parts (behaviour unchanged).

planner_core keeps Proposal, Memory (saved memory and memstore name them
there) and the three rules that build Proposals (_stuck_again_rule,
_restraint_order, _soldier_swap); everything else moved to
planner_core_{base,rules,threats,fort,refusals,outcomes} and is re-exported.
"""

from __future__ import annotations

import hashlib
import itertools
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAIN = ROOT / "brain"
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from py_parts import py_parts  # noqa: E402

sys.path.insert(0, str(BRAIN))
import planner  # noqa: E402
import planner_core  # noqa: E402

PARTS = ["planner_core_base", "planner_core_rules", "planner_core_threats", "planner_core_fort",
         "planner_core_refusals", "planner_core_outcomes"]
KEPT = {"Proposal", "Memory", "_stuck_again_rule", "_restraint_order", "_soldier_swap"}

# dir(planner_core) at 6298b4a (0.105.62), dunder names left out
NAMES_6298B4A = """
    ADJUST_BOUNDS AGENDA_THEMES ALL_FOOD BREW_RECIPES BUILDABLE_SHOPS COOLDOWN_KEYS CROWD_LOCATIONS
    DISPOSAL_ACTION_MAX DISPOSAL_LEVELS EMERGENCY GEAR_METALS GEAR_WEAPONS GREAT_LIKE_KINDS
    IDLE_OLD_LINES JOB_SHOPS LABOR_CAPS LIMIT_EXEMPT LOCATION_UNITS LOOP_EXEMPT LOOP_LIMITS
    LOOP_LIMIT_DEFAULT MAINTAIN_SKIPS MANDATE_RECIPES MEAL_RECIPES MEMORIAL_SPAN MINING_NEED_ONLY
    MOOD_BODY_FLAGS MULTI_PER_CYCLE Memory NEEDS_YOU NO_COOLDOWN NO_EFFECT_RULES NO_EFFECT_WHY
    ONE_A_CYCLE OPEN_CAVERNS_MODES OPTIONAL_LEVELS ORDER_HOLD_EXEMPT OWN_PACE PER_ID_COOLDOWN
    PLANNER_CONFIG Proposal RAW_FOOD RECIPE_SHOPS REFUSAL_FIRST_DAYS REFUSAL_IDLE_DAYS REFUSAL_ID_TYPES
    REFUSAL_KEYS REFUSAL_MAX_DAYS SHOP_ALIASES SOCIAL_NEEDS STALE_PROJECT_DAYS STEER_MAX_DAYS
    STEER_PROTECTED STUCK_HOLD_EXEMPT SURVIVAL_SHOPS TICKS_PER_DAY TICKS_PER_YEAR TIMEOUT_TRIES
    WINTER_STOCK WOOD_ELSEWHERE WORKED_MAX_DAYS ZONE_FULL_FIRST_DAYS ZONE_FULL_MAX_DAYS _best_metal
    _clamp _d _entrance_spot _has_shop _holding_off _idle_free_known _idle_share _is_cavern _key_value
    _l _lever_state _location _location_short _lone_thieves _loop_count _num_ _number _office_held
    _real_locations _record_any_outcome _refused_wait _restraint_order _soldier_swap _stalled_days
    _stuck_again_rule _stuck_before _traits _watchdog_notes _weapon_gaps _wild_free_squads
    _workshops_busy abs_tick agenda all_clear annotations asdict ask_player brew_recipe brewable_counts
    brief_timeout can_fight care_waiting cooldown_key crowded_thief dataclass effective_config emergency
    established factor field food_per_dwarf free_stock game_day great_present growth_mode growth_target
    has_farms has_rule held_off_threats idle_line is_ranged is_release jobs_reported json justice_held
    labor_given level_refused levels_done limit_exempt manager_needs_office masons_jammed math
    mining_plan mood_kind mood_on_hand mood_waits no_effect_wait noble_room_kinds normalize
    note_labor_given note_no_effect note_refusal note_zone_full open_caverns_mode order_job_state
    player_rules queued reachable_threats recently_home recipe_shop refusal_key shop_count shops_max
    snatcher_ids spare_sig stamp_tick steer_of steer_protected stone_short stuck_days stuck_hold_days
    suites_short supply_order_kept tantrums_recent thief_ids thief_rows thread_plants_here
    timeout_streak unmet unstored_cups update_idle watch_since wild_pack wild_rows wildlife_threat
    wildlife_threats winter_factor wool_route young_fort zone_full_days
""".split()
ALL_MD5_6298B4A = "7996653a5a0932c23cdaffc464194aa3"     # "\\n".join(planner_core.__all__) at 6298b4a


def _names(mod) -> list:
    return sorted(n for n in dir(mod) if not (n.startswith("__") and n.endswith("__")))


@test("planner_core exposes exactly the names it had at 6298b4a, and the same __all__")
def _():
    assert len(NAMES_6298B4A) == 184
    now = _names(planner_core)
    assert now == sorted(NAMES_6298B4A), (set(now) ^ set(NAMES_6298B4A))
    assert hashlib.md5("\n".join(planner_core.__all__).encode()).hexdigest() == ALL_MD5_6298B4A


def _assigned(p: str) -> set:
    import ast
    out = set()
    for n in ast.parse((BRAIN / f"{p}.py").read_text(encoding="utf-8")).body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Assign):
            out |= {t.id for t in n.targets if isinstance(t, ast.Name)}
    return out


@test("every name a part defines is the same object in planner_core (and in planner where it reaches it)")
def _():
    import importlib
    seen, bad = {}, []
    for p in PARTS:
        mod = importlib.import_module(p)
        own = sorted(_assigned(p))
        assert own, p
        for n in own:
            assert n not in seen, (n, seen.get(n), p)
            seen[n] = p
            if getattr(planner_core, n, None) is not getattr(mod, n):
                bad.append(f"planner_core.{n}")
            if n in planner_core.__all__ and getattr(planner, n, None) is not getattr(mod, n):
                bad.append(f"planner.{n}")
    assert not bad, bad
    # every original name is either kept in planner_core, moved to one part, or an import planner_core had
    imported = {"annotations", "json", "math", "asdict", "dataclass", "field", "has_rule", "_d", "_l", "normalize",
                "PLANNER_CONFIG", "DISPOSAL_ACTION_MAX"}
    assert set(NAMES_6298B4A) == set(seen) | KEPT | imported, set(NAMES_6298B4A) ^ (set(seen) | KEPT | imported)
    assert not (set(seen) & KEPT)
    assert py_parts("planner_core") == PARTS


@test("Proposal and Memory stay in planner_core (saved memory, memstore), as do the rules that build Proposals")
def _():
    for n in KEPT:
        assert getattr(planner_core, n).__module__ == "planner_core", n
    assert planner.Proposal is planner_core.Proposal and planner.Memory is planner_core.Memory
    import memstore
    assert memstore.Memory is planner_core.Memory


@test("planner_core and each part are under 60 KB")
def _():
    for p in ["planner_core"] + PARTS:
        size = (BRAIN / f"{p}.py").stat().st_size
        assert size < 60 * 1024, (p, size)


@test("planner_core and its parts import cleanly in a fresh interpreter, in any order")
def _():
    mods = ["planner_core"] + PARTS
    orders = [[m] + [x for x in mods if x != m] for m in mods] + [list(reversed(mods))]
    orders += [list(o) for o in itertools.islice(itertools.permutations(mods), 0, 5040, 997)]
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import importlib\n"
            "for m in sys.argv[2:]: importlib.import_module(m)\n"
            "import planner_core as c\n"
            "assert len([n for n in dir(c) if not (n.startswith('__') and n.endswith('__'))]) == 184\n"
            "import planner\nassert planner.Memory is c.Memory\n")
    for o in orders:
        r = subprocess.run([sys.executable, "-c", code, str(BRAIN)] + o, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, (o, r.stderr[-1500:])


@test("the parts never import planner_core (no cycle: planner_core imports them)")
def _():
    for p in PARTS:
        src = (BRAIN / f"{p}.py").read_text(encoding="utf-8")
        assert "import planner_core\n" not in src and "from planner_core import" not in src, p


if __name__ == "__main__":
    finish()
