"""(r7 d5) brain/planner_military.py and brain/planner_gates.py split into
parts by theme, behaviour unchanged:

  planner_military -> planner_military_squads, planner_military_threats
  planner_gates    -> planner_gates_stuck, planner_gates_lockdown

Each original still holds exactly the names it had at 6298b4a (dir() and
__all__, recorded here), each moved name is the part's own object, every
global a moved function reads is the object the original reads by that name
(so it resolves as before the move), the code moved whole (the top-level
statements, by their AST, are the ones at 6298b4a), the names other tests
patch on the originals (planner_military fight_or_hide / _gate_rules,
planner_gates profile_from) are still read by code living there, every file
is under 60 KB, and the modules import cleanly in a fresh interpreter in any
order.

    python tests/test_r7_d5.py
"""

from __future__ import annotations

import ast
import dis
import hashlib
import importlib
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
from py_parts import PY_PARTS, py_family  # noqa: E402

ORIGINALS = ("planner_military", "planner_gates")
SIZE_LIMIT = 60 * 1024

# dir() of each original at 6298b4a
NAMES = {
    "planner_military": ["ADJUST_BOUNDS", "AGENDA_THEMES", "ALERT_DANGERS", "ALL_FOOD", "BASE_DWARF", "BREW_RECIPES",
    "BUILDABLE_SHOPS", "COOLDOWN_KEYS", "CROWD_LOCATIONS", "DISPOSAL_ACTION_MAX", "DISPOSAL_LEVELS",
    "DWARF_SIZE", "EMERGENCY", "FIGHT_FACTOR_MAX", "GATEHOUSE_WAGON", "GATE_PART_RECIPES",
    "GATE_PART_STUCK_DAYS", "GATE_STUCK_TRIED", "GEAR_HELD", "GEAR_METALS", "GEAR_WEAPONS", "GREAT_ABILITY",
    "GREAT_BASE", "GREAT_FLIER", "GREAT_KIND", "GREAT_LIKE_KINDS", "IDLE_OLD_LINES", "JOB_SHOPS",
    "LABOR_CAPS", "LIMIT_EXEMPT", "LOCATION_UNITS", "LOOP_EXEMPT", "LOOP_LIMITS", "LOOP_LIMIT_DEFAULT",
    "MAINTAIN_SKIPS", "MANDATE_RECIPES", "MEAL_RECIPES", "MEMORIAL_SPAN", "MINING_NEED_ONLY",
    "MOOD_BODY_FLAGS", "MULTI_PER_CYCLE", "Memory", "NEEDS_YOU", "NO_COOLDOWN", "NO_EFFECT_RULES",
    "NO_EFFECT_WHY", "ONE_A_CYCLE", "OPEN_CAVERNS_MODES", "OPTIONAL_LEVELS", "ORDER_HOLD_EXEMPT",
    "PASTURE_ACTIONS", "PER_ID_COOLDOWN", "PLANNER_CONFIG", "Proposal", "RAW_FOOD", "RECIPE_SHOPS",
    "REFUSAL_FIRST_DAYS", "REFUSAL_IDLE_DAYS", "REFUSAL_ID_TYPES", "REFUSAL_KEYS", "REFUSAL_MAX_DAYS",
    "SHELTER_RETRY_DAYS", "SHELTER_RETRY_THREAT_DAYS", "SHOP_ALIASES", "SMALL_FLOOR", "SOCIAL_NEEDS",
    "STALE_PROJECT_DAYS", "STEER_MAX_DAYS", "STEER_PROTECTED", "STRANDED_CONFIG", "STUCK_HOLD_EXEMPT",
    "SURVIVAL_SHOPS", "TICKS_PER_DAY", "TICKS_PER_YEAR", "TIMEOUT_TRIES", "WAY_IN_KINDS", "WEAPON_IDS",
    "WINTER_STOCK", "WOOD_ELSEWHERE", "ZONE_FULL_FIRST_DAYS", "ZONE_FULL_MAX_DAYS", "_Rec", "__all__",
    "__builtins__", "__cached__", "__doc__", "__file__", "__loader__", "__name__", "__package__", "__spec__",
    "_alerts_rule", "_anvil_rule", "_base_power", "_best_metal", "_bowyer_rule", "_clamp", "_crossbow_order",
    "_crossing_rule", "_d", "_entrance_spot", "_fight_outcome", "_free_gate_levers", "_gate_dogs_rule",
    "_gate_guard_rule", "_gate_parts_rule", "_gate_rules", "_gatehouse_rule", "_has_shop", "_hazard_rules",
    "_holding_off", "_idle_share", "_l", "_lever_far_enough", "_lever_hatches_ok", "_lever_rule",
    "_lever_state", "_link_wanted", "_location", "_location_short", "_lockdown", "_lockdown_cap_why",
    "_lockdown_ids", "_lone_squad", "_loop_count", "_military_rules", "_near_spot", "_no_melee_beasts",
    "_no_shelter_note", "_note_fight", "_number", "_office_held", "_one_enemy_hold", "_pasture_hold",
    "_players", "_ranged_squad_rule", "_real_locations", "_record_any_outcome", "_refused_wait",
    "_restraint_order", "_second_way_rule", "_shelter_due", "_shelter_possible", "_shoots", "_soldier_swap",
    "_soldiers_wanted", "_stalled_days", "_stranded_rule", "_stuck_again_rule", "_stuck_before",
    "_train_mode_held", "_training_rotation", "_traits", "_trap_rule", "_uniform_weapon_rule",
    "_war_animal_rule", "_watchdog_notes", "_weapon_gaps", "_workshops_busy", "abs_tick", "agenda",
    "ai_gates_shut", "alert_ages", "all_clear", "annotations", "asdict", "ask_player", "brew_recipe",
    "brewable_counts", "brief_timeout", "called_off_ids", "can_fight", "care_waiting", "civilian_cap",
    "cooldown_key", "crossbows_wanted", "crossing_value", "crowded_thief", "dataclass", "destroyer_gate_due",
    "effective_config", "emergency", "established", "factor", "facts_mult", "few_alert_over", "few_near",
    "few_ordinary", "field", "fight_key", "fight_or_hide", "food_per_dwarf", "fort_years", "free_stock",
    "game_day", "gate_invaders", "gatehouse_asked", "gatehouse_wanted", "great_present", "growth_mode",
    "growth_target", "has_farms", "has_rule", "hazard_alert", "held_levels", "held_off_threats",
    "hunted_outside", "idle_hands", "idle_line", "is_ranged", "is_release", "jobs_reported", "json", "judge",
    "justice_held", "keen_lift", "labor_given", "layout_style", "level_refused", "levels_done",
    "limit_exempt", "lockdown_released", "lone_alert_over", "lone_intruders", "machinery_wanted", "main_gate",
    "manager_needs_office", "masons_jammed", "masterplan", "matchup", "math", "mining_plan", "mood_kind",
    "mood_on_hand", "mood_waits", "new_history", "no_effect_wait", "no_melee_great", "no_shelter",
    "noble_room_kinds", "normalize", "note_gate_stuck", "note_gate_stuck_cycle", "note_labor_given",
    "note_lockdown", "note_no_effect", "note_ranged_need", "note_refusal", "note_second_way",
    "note_zone_full", "open_caverns_mode", "order_job_state", "phases", "pick_stone", "player_gate_row",
    "player_rules", "profile_from", "queued", "quick_clear", "re", "reachable_threats", "recently_home",
    "recipe_shop", "refusal_key", "shop_count", "shops_max", "snatcher_ids", "soldier_share",
    "soldiers_wanted", "sortie_out", "spare_sig", "split_pieces", "stamp_tick", "steer_of", "steer_protected",
    "stone_for", "stone_short", "stuck_days", "stuck_hold_days", "stuck_rows", "suites_short",
    "supply_order_kept", "tantrums_recent", "thief_ids", "thief_rows", "thread_plants_here", "threat_power",
    "timeout_streak", "unmet", "unstored_cups", "update_idle", "watch_since", "watched_gate_levers",
    "weak_squad", "wild_pack", "wild_rows", "wildlife_threat", "wildlife_threats", "winter_factor",
    "wool_route", "young_fort", "zone_full_days"],
    "planner_gates": ["ADJUST_BOUNDS", "AGENDA_THEMES", "ALL_FOOD", "BREW_RECIPES", "BUILDABLE_SHOPS", "COOLDOWN_KEYS",
    "CROWD_LOCATIONS", "DISPOSAL_ACTION_MAX", "DISPOSAL_LEVELS", "EMERGENCY", "GATEHOUSE_WAGON",
    "GATE_PART_RECIPES", "GATE_PART_STUCK_DAYS", "GATE_STUCK_TRIED", "GEAR_METALS", "GEAR_WEAPONS",
    "GREAT_LIKE_KINDS", "IDLE_OLD_LINES", "JOB_SHOPS", "LABOR_CAPS", "LIMIT_EXEMPT", "LOCATION_UNITS",
    "LOOP_EXEMPT", "LOOP_LIMITS", "LOOP_LIMIT_DEFAULT", "MAINTAIN_SKIPS", "MANDATE_RECIPES", "MEAL_RECIPES",
    "MEMORIAL_SPAN", "MINING_NEED_ONLY", "MOOD_BODY_FLAGS", "MULTI_PER_CYCLE", "Memory", "NEEDS_YOU",
    "NO_COOLDOWN", "NO_EFFECT_RULES", "NO_EFFECT_WHY", "ONE_A_CYCLE", "OPEN_CAVERNS_MODES", "OPTIONAL_LEVELS",
    "ORDER_HOLD_EXEMPT", "PASTURE_ACTIONS", "PER_ID_COOLDOWN", "PLANNER_CONFIG", "PREVENT_BACKOFF_DAYS",
    "Proposal", "RAW_FOOD", "RECIPE_SHOPS", "REFUSAL_FIRST_DAYS", "REFUSAL_IDLE_DAYS", "REFUSAL_ID_TYPES",
    "REFUSAL_KEYS", "REFUSAL_MAX_DAYS", "SHOP_ALIASES", "SOCIAL_NEEDS", "STALE_PROJECT_DAYS",
    "STEER_MAX_DAYS", "STEER_PROTECTED", "STRANDED_CONFIG", "STUCK_HOLD_EXEMPT", "SURVIVAL_SHOPS",
    "TICKS_PER_DAY", "TICKS_PER_YEAR", "TIMEOUT_TRIES", "WAY_IN_KINDS", "WINTER_STOCK", "WOOD_ELSEWHERE",
    "ZONE_FULL_FIRST_DAYS", "ZONE_FULL_MAX_DAYS", "_Rec", "__all__", "__builtins__", "__cached__", "__doc__",
    "__file__", "__loader__", "__name__", "__package__", "__spec__", "_best_metal", "_clamp", "_d",
    "_entrance_spot", "_flags_text", "_free_gate_levers", "_gate_dogs_rule", "_gate_guard_rule",
    "_gate_parts_rule", "_gate_rules", "_gate_stuck_rule", "_gatehouse_rule", "_has_shop", "_holding_off",
    "_idle_share", "_l", "_lever_far_enough", "_lever_hatches_ok", "_lever_rule", "_lever_state",
    "_link_wanted", "_location", "_location_short", "_lockdown", "_lockdown_cap_why", "_lockdown_ids",
    "_loop_count", "_near_spot", "_number", "_office_held", "_pasture_hold", "_reach_lift", "_real_locations",
    "_record_any_outcome", "_refused_wait", "_restraint_order", "_row_danger", "_second_way_rule",
    "_soldier_swap", "_sortie_on", "_stalled_days", "_stranded_relook", "_stranded_rule", "_stuck_again_rule",
    "_stuck_before", "_surface_entrances", "_traits", "_trap_rule", "_watchdog_notes", "_way_in_area",
    "_way_in_doing", "_way_in_rule", "_weapon_gaps", "_wings_rule", "_workshops_busy", "abs_tick", "agenda",
    "ai_gates_shut", "all_clear", "annotations", "ask_player", "brew_recipe", "brewable_counts",
    "brief_timeout", "can_fight", "care_waiting", "cavern_wall_style", "cooldown_key", "crowded_thief",
    "destroyer_gate_due", "effective_config", "emergency", "established", "factor", "few_alert_over",
    "few_near", "few_ordinary", "field", "food_per_dwarf", "fort_years", "free_stock", "game_day",
    "gate_exhausted", "gate_invaders", "gatehouse_asked", "gatehouse_wanted", "great_present", "growth_mode",
    "growth_target", "has_farms", "has_rule", "held_off_threats", "hunted_outside", "idle_line", "is_ranged",
    "is_release", "jobs_reported", "justice_held", "labor_given", "level_refused", "levels_done",
    "limit_exempt", "lockdown_released", "lone_alert_over", "lone_intruders", "machinery_wanted", "main_gate",
    "manager_needs_office", "masons_jammed", "mining_plan", "mood_kind", "mood_on_hand", "mood_waits",
    "no_effect_wait", "noble_room_kinds", "note_gate_stuck", "note_gate_stuck_cycle", "note_labor_given",
    "note_lockdown", "note_no_effect", "note_refusal", "note_second_way", "note_zone_full",
    "open_caverns_mode", "order_job_state", "player_gate_row", "player_rules", "profile_from", "queued",
    "quick_clear", "reachable_threats", "recently_home", "recipe_shop", "refusal_key", "shop_count",
    "shops_max", "snatcher_ids", "sortie_out", "spare_sig", "split_pieces", "stamp_tick", "steer_of",
    "steer_protected", "stone_short", "stuck_days", "stuck_hold_days", "stuck_rows", "suites_short",
    "supply_order_kept", "tantrums_recent", "thief_ids", "thief_rows", "thread_plants_here", "timeout_streak",
    "unmet", "unstored_cups", "update_idle", "watch_since", "wild_pack", "wild_rows", "wildlife_threat",
    "wildlife_threats", "winter_factor", "wool_route", "young_fort", "zone_full_days"],
}
# __all__ of each original at 6298b4a (order kept)
ALL = {
    "planner_military": ["called_off_ids", "FIGHT_FACTOR_MAX", "lone_intruders", "hunted_outside", "few_ordinary", "few_alert_over",
    "ai_gates_shut", "lockdown_released", "lone_alert_over", "note_lockdown", "_lone_squad", "quick_clear",
    "PASTURE_ACTIONS", "_pasture_hold", "gate_invaders", "main_gate", "_gate_guard_rule", "_gate_dogs_rule",
    "GEAR_HELD", "_shelter_possible", "no_shelter", "SHELTER_RETRY_DAYS", "SHELTER_RETRY_THREAT_DAYS",
    "_shelter_due", "_no_shelter_note", "weak_squad", "soldier_share", "_gate_rules", "_free_gate_levers",
    "_lever_far_enough", "_link_wanted", "_lever_rule", "_trap_rule", "_gatehouse_rule", "_lever_hatches_ok",
    "_near_spot", "soldiers_wanted", "civilian_cap", "crossing_value", "_crossing_rule", "ALERT_DANGERS",
    "alert_ages", "_alerts_rule", "_war_animal_rule", "hazard_alert", "_hazard_rules", "_military_rules",
    "watched_gate_levers", "_training_rotation", "_ranged_squad_rule", "note_ranged_need", "crossbows_wanted",
    "_bowyer_rule", "_crossbow_order", "WEAPON_IDS", "_uniform_weapon_rule", "_anvil_rule", "idle_hands"],
    "planner_gates": ["sortie_out", "_gate_rules", "_stranded_rule", "player_gate_row", "split_pieces", "stuck_rows",
    "note_gate_stuck", "note_gate_stuck_cycle", "note_second_way", "_second_way_rule", "WAY_IN_KINDS",
    "GATE_STUCK_TRIED", "STRANDED_CONFIG", "GATE_PART_RECIPES", "GATE_PART_STUCK_DAYS", "_gate_parts_rule",
    "_free_gate_levers", "_lever_far_enough", "machinery_wanted", "_lever_hatches_ok", "_link_wanted",
    "_lever_rule", "_trap_rule", "_gatehouse_rule", "fort_years", "destroyer_gate_due", "gatehouse_wanted",
    "gatehouse_asked", "GATEHOUSE_WAGON", "_near_spot", "lone_intruders", "few_ordinary", "few_alert_over",
    "few_near", "hunted_outside", "ai_gates_shut", "_Rec", "_lockdown", "lockdown_released",
    "lone_alert_over", "_lockdown_ids", "_lockdown_cap_why", "note_lockdown", "quick_clear",
    "PASTURE_ACTIONS", "_pasture_hold", "gate_invaders", "main_gate", "_gate_guard_rule", "_gate_dogs_rule"],
}
# the top-level statements of both originals at 6298b4a (imports, __all__ and
# the module docstrings left out): how many, and the md5 of their sorted AST md5s
BASE_NODES = (123, "e746545754b955b60695c33c70c1b03e")


def _defined(name: str) -> list[str]:
    """The names a module's own top level defines (def, class, plain assignment)."""
    t = ast.parse((ROOT / "brain" / f"{name}.py").read_text(encoding="utf-8"))
    out = []
    for n in t.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            out.append(n.name)
        elif isinstance(n, ast.Assign):
            out += [x.id for x in n.targets if isinstance(x, ast.Name) and x.id != "__all__"]
    return out


@test("r7 d5: each original exposes exactly the names (dir and __all__) it had at 6298b4a")
def _():
    for name in ORIGINALS:
        m = importlib.import_module(name)
        got = sorted(dir(m))
        assert got == sorted(NAMES[name]), (name, sorted(set(got) ^ set(NAMES[name])))
        assert list(m.__all__) == ALL[name], name


@test("r7 d5: every name a part defines is the same object in the original (and in planner when exported)")
def _():
    import planner
    import planner_military
    for name in ORIGINALS:
        m = importlib.import_module(name)
        for part in PY_PARTS[name]:
            p = importlib.import_module(part)
            names = _defined(part)
            assert names, part
            assert sorted(p.__all__) == sorted(n for n in names if not n.startswith("_")), part
            for n in names:
                assert getattr(m, n) is getattr(p, n), (name, part, n)
                if n in planner_military.__all__:          # (planner takes planner_military's __all__)
                    assert getattr(planner, n) is getattr(p, n), ("planner", n)
            for n in names:
                obj = getattr(p, n)
                if isinstance(obj, (types.FunctionType, type)):
                    assert obj.__module__ == part, (part, n, obj.__module__)


@test("r7 d5: every global a moved function reads is the object the original has by that name")
def _():
    import builtins
    for name in ORIGINALS:
        m = importlib.import_module(name)
        for part in PY_PARTS[name]:
            p = importlib.import_module(part)
            bad = []

            def walk(code, where):
                for ins in dis.get_instructions(code):
                    if ins.opname in ("LOAD_GLOBAL", "LOAD_NAME", "STORE_GLOBAL"):
                        n = str(ins.argval).replace(" + NULL", "").replace("NULL + ", "")
                        if n in p.__dict__:
                            if n in m.__dict__ and p.__dict__[n] is not m.__dict__[n] and not n.startswith("__"):
                                bad.append(f"{where}: {n} differs")
                            if n not in m.__dict__:
                                bad.append(f"{where}: {n} not in {name}")
                        elif not hasattr(builtins, n):
                            bad.append(f"{where}: {n} unresolved")
                for c in code.co_consts:
                    if isinstance(c, types.CodeType):
                        walk(c, f"{where}.{c.co_name}")
            for n in _defined(part):
                obj = getattr(p, n)
                if isinstance(obj, types.FunctionType):
                    walk(obj.__code__, f"{part}.{n}")
                elif isinstance(obj, type):
                    for v in vars(obj).values():
                        if isinstance(v, types.FunctionType):
                            walk(v.__code__, f"{part}.{n}.{v.__name__}")
            assert not bad, bad


@test("r7 d5: the code moved whole (the top-level statements are those of 6298b4a, by their AST)")
def _():
    hs = []
    for name in ORIGINALS:
        for f in py_family(name):
            t = ast.parse((ROOT / "brain" / f"{f}.py").read_text(encoding="utf-8"))
            for i, n in enumerate(t.body):
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    continue
                if i == 0 and isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
                    continue
                if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "__all__":
                    continue
                hs.append(hashlib.md5(ast.dump(n).encode()).hexdigest())
    got = (len(hs), hashlib.md5("\n".join(sorted(hs)).encode()).hexdigest())
    assert got == BASE_NODES, got


@test("r7 d5: the names other tests patch on the originals are still read by code living there")
def _():
    import planner_gates
    import planner_military
    # test_fix26_features patches planner_military.fight_or_hide, test_k48_cycle_guards
    # planner_military._gate_rules: both are read by _military_rules, which stays
    assert planner_military._military_rules.__module__ == "planner_military"
    names = planner_military._military_rules.__code__.co_names
    assert "fight_or_hide" in names and "_gate_rules" in names
    # test_r47_traps_alarms patches planner_gates.profile_from for _trap_rule (and
    # _gatehouse_rule / _gate_rules read it): all three stay in planner_gates
    for n in ("_trap_rule", "_gatehouse_rule", "_gate_rules"):
        f = getattr(planner_gates, n)
        assert f.__module__ == "planner_gates" and "profile_from" in f.__code__.co_names, n
    # no moved function reads one of those patched names (the patch would miss it)
    for name, patched in (("planner_military", ("fight_or_hide", "_gate_rules", "fight_bar")),
                          ("planner_gates", ("profile_from",))):
        for part in PY_PARTS[name]:
            p = importlib.import_module(part)
            for n in _defined(part):
                obj = getattr(p, n)
                if isinstance(obj, types.FunctionType):
                    assert not set(patched) & set(obj.__code__.co_names), (part, n)


@test("r7 d5: every original and part is under 60 KB")
def _():
    for name in ORIGINALS:
        for f in py_family(name):
            size = (ROOT / "brain" / f"{f}.py").stat().st_size
            assert size < SIZE_LIMIT, (f, size)


@test("r7 d5: the modules import cleanly in a fresh interpreter, whichever comes first")
def _():
    mods = [f for name in ORIGINALS for f in py_family(name)]
    orders = [[m] + [x for x in mods if x != m] for m in mods] + [list(reversed(mods)), ["planner"] + mods]
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import importlib\n"
            "for m in sys.argv[2:]: importlib.import_module(m)\n"
            "import planner_military, planner_gates\n"
            "assert sorted(dir(planner_military)) == sorted(sys.modules['__main__'].N1)\n")
    for order in orders:
        r = subprocess.run([sys.executable, "-c", "N1 = %r\n" % (NAMES["planner_military"],) + code,
                            str(ROOT / "brain"), *order], capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, (order, r.stderr[-800:])


finish()
