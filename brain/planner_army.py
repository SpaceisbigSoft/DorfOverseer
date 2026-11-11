"""(0.105.0, round 2) An army that can fight.

Enemies are on in the new fort, and Teacheroar's live report (1 Nov) showed
an army that couldn't: 39 soldiers, 23 armed, 16 weapon places the game
left empty and "0 fillable" while 8 battle axes lay spare; nobody with a
shield though 4 lay spare; a crossbow squad with no quivers; bolts left at
the bowyer's; and when the AI hid from a titan the squads stood about
wherever they were. Here:

  * the gaps' reasons (the bridge's `weapon_gaps_why`, one per empty entry)
    are acted on: stale claims cleared, a material the fort hasn't got
    loosened, a shield entry for the metal squads while shields lie spare,
    the weapon the entries name ordered when there is none of it at all, and
    the player told what the AI can't mend (unreachable, forbidden);
  * quivers: a free one put on each crossbow soldier's place (the place's
    own quiver field: a quiver is not part of a uniform), leather ones made
    when there are too few;
  * bolts: a crossbow squad with no ammunition entry gets one;
  * hiding: the squads hold the civilian alert's shelter with the civilians
    while the AI hides from a great danger, and come out when the alert
    clears or the squads go to fight (Rules tab: "When hiding, squads
    wait in the shelter");
  * gates: an opening too wide to wall, or one refused for what stands in
    it, is cut where its open area leads down into the fort: a hatch on
    each stair down (lua/ai-gates.lua plan_cut), which the gate watcher
    locks like any other gate.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (AGENDA_THEMES, GEAR_WEAPONS, Proposal, all_clear, can_fight, is_ranged, player_rules, queued,
                          reachable_threats, _has_shop)

__all__ = ["_army_gear_rule", "_quiver_rule", "_bolts_rule", "_shelter_squads_rule", "_gate_cut_rule",
           "hiding", "danger_close", "_flask_rule", "WEAPON_RECIPES"]

AGENDA_THEMES.update({"gear_fix": "arm the soldiers", "quivers": "quivers for the crossbows",
                      "bolts": "bolts for the crossbows", "shelter_squads": "the squads hide with the civilians",
                      "gate_cut": "close the wide openings"})

# the weapon an entry names, and how the fort makes it
WEAPON_RECIPES = {"ITEM_WEAPON_AXE_BATTLE": "metal_battle_axe", "ITEM_WEAPON_SPEAR": "metal_spear",
                  "ITEM_WEAPON_MACE": "metal_mace", "ITEM_WEAPON_CROSSBOW": "wooden_crossbow"}

# reasons the AI mends itself (lua/ai-military.lua fix_gear_gaps)
FIXABLE = ("stale on a soldier's list", "wrong material", "fillable",
           # (0.105.2) forbidden or dumped weapons let go (none set to melt, none near enemies)
           "forbidden, dumped or to melt")


def _why(gear: dict) -> dict:
    return {k: int(v) for k, v in _d(gear.get("weapon_gaps_why")).items()
            if isinstance(v, int) and not isinstance(v, bool) and v > 0}


def _army_gear_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """The empty weapon entries, by the bridge's reasons; and the shields."""
    mil = _d(s.get("military"))
    g = _d(mil.get("gear"))
    rules_ = player_rules(s)
    if not rules_["make_gear"] or "error" in g or not int(g.get("on_duty") or g.get("soldiers") or 0):
        return
    why = _why(g)
    squads = [q for q in _l(mil.get("squads")) if isinstance(q, dict)]
    sh = _d(g.get("shields"))
    spare_shields = int(_d(g.get("spare")).get("shields") or 0)
    metal_melee = [q for q in squads if "metal" in str(q.get("ai_uniform") or "").lower() and not is_ranged(q)
                   and (q.get("members") or 0) > 0]
    # (0.105.0 review) the places without a shield entry that add_shields mends
    # are the metal melee squads' only: a crossbow or player squad's don't count
    by_squad = sh.get("no_entry_squads")
    if isinstance(by_squad, dict):
        no_entry = sum(int(by_squad.get(str(q.get("id"))) or 0) for q in metal_melee)
    else:
        no_entry = int(sh.get("no_entry") or 0)          # (an older bridge: the fort's count)
    shields = bool(spare_shields > 0 and no_entry > 0 and metal_melee)
    fix = sum(why.get(k, 0) for k in FIXABLE)
    if fix or shields:
        bits = [f"{why[k]} {k}" for k in FIXABLE if why.get(k)]
        if shields:
            bits.append(f"{spare_shields} spare shields and no shield in the metal uniforms")
        proposals.append(Proposal("gear_fix", {"type": "fix_gear_gaps", "shields": shields},
                                  f"{int(g.get('weapon_gaps') or 0)} soldier place(s) without a weapon ("
                                  + "; ".join(bits) + "): mend the uniforms and hand the gear out", 3))
    # an entry naming a weapon the fort has none of at all: make it
    wanted = {k: int(v) for k, v in _d(g.get("weapon_gaps_wanted")).items() if isinstance(v, int) and v > 0}
    bars = _d(g.get("bars"))
    for wid, n in sorted(wanted.items(), key=lambda x: -x[1]):
        recipe = WEAPON_RECIPES.get(wid)
        if not recipe or queued(s, {recipe}):
            continue
        n = min(n, cfg["max_gear_order"])
        if recipe == "wooden_crossbow":
            if _has_shop(s["buildings"], "Bowyers") and int(_d(s.get("stocks")).get("wood") or 0) >= n:
                proposals.append(Proposal("gear_fix_order", {"type": "work_order", "recipe": recipe, "amount": n},
                                          f"{n} crossbow place(s) and no crossbow to give: make {n} at the bowyer's",
                                          3, True))
            break
        metal = next((m for m in ("STEEL", "IRON", "BRONZE", "BISMUTH_BRONZE", "COPPER")
                      if (bars.get(m) or 0) >= n * 2), None)
        if metal and g.get("forges"):
            proposals.append(Proposal("gear_fix_order", {"type": "work_order", "recipe": recipe, "amount": n,
                                                          "material": f"INORGANIC:{metal}"},
                                      f"{n} soldier place(s) ask for {wid.split('_')[-1].lower()}s and the fort has "
                                      f"none: make {n} in {metal.lower().replace('_', ' ')}", 3, True))
        break
    if why.get("unreachable"):
        # (0.105.35) nothing waits for the player: weapons they can reach are
        # made for them (the AI's weapon, in the best metal with bars enough)
        n = min(why["unreachable"], cfg["max_gear_order"])
        recipe = GEAR_WEAPONS.get(rules_["gear_weapon"], "metal_battle_axe")
        metal = next((m for m in ("STEEL", "IRON", "BRONZE", "BISMUTH_BRONZE", "COPPER")
                      if (bars.get(m) or 0) >= n * 2), None)
        made = any(p.rule == "gear_fix_order" for p in proposals) or queued(s, {recipe})
        # (a weapon pile they can't reach would take every new one too: none
        # made once twice as many of the AI's weapon lie spare)
        from planner_military import WEAPON_IDS
        spare_ai = int(_d(g.get("spare_weapons")).get(WEAPON_IDS.get(rules_["gear_weapon"])) or 0)
        if spare_ai >= 2 * max(1, why["unreachable"]):
            notes.append(f"{why['unreachable']} soldier(s) can't get to the free weapons (behind a closed door "
                         f"or outside the gates) and {spare_ai} lie spare: no more made while that many lie "
                         "spare")
        elif metal and g.get("forges") and not made:
            proposals.append(Proposal("gear_fix_order", {"type": "work_order", "recipe": recipe, "amount": n,
                                                          "material": f"INORGANIC:{metal}"},
                                      f"{why['unreachable']} soldier(s) can't get to the free weapons (behind a "
                                      f"closed door or outside the gates): make {n} they can reach, in "
                                      f"{metal.lower().replace('_', ' ')}", 3, True))
        else:
            notes.append(f"{why['unreachable']} soldier(s) can't get to the free weapons (behind a closed door "
                         "or outside the gates): "
                         + ("new ones are on order" if made else "new ones are made once there is a forge and bars"))
    if why.get("forbidden, dumped or to melt"):
        notes.append(f"{why['forbidden, dumped or to melt']} weapon place(s) wait on weapons that are forbidden, "
                     "dumped or set to melt: the forbidden and dumped are let go when no enemy is near "
                     "(those set to melt go to the smelter; new ones are made in their place)")


def _quiver_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """A quiver on each crossbow soldier's place: free ones handed out, leather
    ones made (bridge 0.105.0: `ranged_places`, `quivers_assigned`, `quivers_free`)."""
    g = _d(_d(s.get("military")).get("gear"))
    if not isinstance(g.get("ranged_places"), int) or "error" in g:
        return
    need = g["ranged_places"] - int(g.get("quivers_assigned") or 0)
    if need <= 0:
        return
    free = int(g.get("quivers_free") or 0)
    if free > 0:
        proposals.append(Proposal("quivers", {"type": "assign_quivers", "limit": min(10, need)},
                                  f"{need} crossbow soldier(s) without a quiver (they can't carry bolts) and "
                                  f"{free} free: give them one", 3))
    short = need - free - queued(s, {"leather_quiver"})
    # the AI's own crossbow squad has its quivers ordered by the 0.100 rule
    # (planner_military _ranged_squad_rule): only a squad it doesn't cover
    ai_ranged = any(is_ranged(q) for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict))
    if short > 0 and player_rules(s)["make_gear"] and not ai_ranged:
        leather = int(_d(s.get("stocks")).get("leather") or 0)
        if leather > 0 and _has_shop(s["buildings"], "Leatherworks"):
            n = min(short, leather, cfg["max_quiver_order"])
            proposals.append(Proposal("quivers_order", {"type": "work_order", "recipe": "leather_quiver", "amount": n},
                                      f"{need} crossbow soldier(s) without a quiver, {free} free: make {n} of "
                                      "leather", 4, True))
        else:
            notes.append(f"{short} crossbow soldier(s) need a quiver: no leather or no leatherworks to make one")


def _flask_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(0.105.26) A waterskin or flask for each soldier: a squad set to carry
    water (carry_water, lua/ai-military.lua) fills nothing without one, and
    nothing made them (B: 28 soldiers died of thirst on the shelter order).
    Bridge: gear `flask_places` (soldiers), `flasks_assigned`, `flasks_free`
    (DF hands the free ones out itself). Leather waterskins at a leather
    works; with no leather, green glass vials at a glass furnace with sand."""
    g = _d(_d(s.get("military")).get("gear"))
    if not isinstance(g.get("flask_places"), int) or "error" in g or not player_rules(s)["make_gear"]:
        return
    short = (g["flask_places"] - int(g.get("flasks_assigned") or 0) - int(g.get("flasks_free") or 0)
             - queued(s, {"leather_waterskin", "glass_vial"}))
    if short <= 0:
        return
    b = s.get("buildings") or {}
    leather = int(_d(s.get("stocks")).get("leather") or 0)
    sup = _d(s.get("supplies"))
    bags, fuel = int(sup.get("sand_bags") or 0), int(sup.get("fuel") or 0)
    # (0.105.31 reserve fixes) leather kept for strange moods isn't spare:
    # glass vials whenever only the reserve (or less) is left, not only at 0
    keep = int(cfg.get("reserve_leather") or 0) if isinstance(_d(s.get("stocks")).get("leather"), int) else 0
    spare = leather - keep
    if spare > 0 and _has_shop(b, "Leatherworks"):
        n = min(short, spare, cfg["max_quiver_order"])
        proposals.append(Proposal("flasks_order", {"type": "work_order", "recipe": "leather_waterskin", "amount": n},
                                  f"{short} soldier(s) without a waterskin or flask (they carry no water out): "
                                  f"make {n} of leather", 4, True))
    elif _has_shop(b, "GlassFurnace") and bags > 0 and fuel > 0:
        n = min(short, bags, fuel, cfg["max_quiver_order"])
        proposals.append(Proposal("flasks_order", {"type": "work_order", "recipe": "glass_vial", "amount": n},
                                  f"{short} soldier(s) without a waterskin or flask (they carry no water out) and "
                                  + ("no leather" if leather <= 0 else f"only the {leather} leather kept for strange moods")
                                  + f": make {n} glass vials", 4, True))
    else:
        notes.append(f"{short} soldier(s) without a waterskin or flask: no leather and leather works, nor glass "
                     "furnace with sand and fuel, to make one")


def _bolts_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """A squad with crossbows and no ammunition entry: bolts for it."""
    for q in _l(_d(s.get("military")).get("squads")):
        if not isinstance(q, dict) or q.get("id") is None or not (q.get("members") or 0):
            continue
        a = q.get("ammo")
        if isinstance(a, dict) and int(a.get("specs") or 0) == 0:
            proposals.append(Proposal("bolts", {"type": "squad_bolts", "squad_id": q["id"]},
                                      f"{q.get('name') or 'a crossbow squad'} has crossbows and no bolts set: "
                                      "bolts for combat and training", 3))
            return
        if (isinstance(a, dict) and int(a.get("wanted") or 0) > 0 and int(a.get("assigned") or 0) == 0
                and int(_d(_d(s.get("military")).get("gear")).get("bolts") or 0) > 0):
            notes.append(f"{q.get('name') or 'a crossbow squad'} has bolts set but none handed out yet "
                         "(they must lie in a stockpile, not a workshop)")


def hiding(s: dict, memory, cfg: dict) -> tuple[bool, list]:
    """(hide, targets): the AI hides when great dangers can reach the dwarves,
    the squads aren't sent at them (fight or hide), and nothing else in reach
    is theirs to fight. Read the same way as _military_rules does."""
    from planner_military import fight_or_hide
    rules_ = player_rules(s)
    traits = _d(_d(s.get("settings")).get("traits"))
    threats = {t.get("id"): t for t in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(t, dict)}
    reach = [i for i in reachable_threats(s, traits, cfg) if i in threats]
    if not reach:
        return False, []
    squads = [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict)]
    able = [q for q in squads if can_fight(q, cfg)]
    great = [i for i in reach if threats[i].get("great_danger")]
    policy = rules_["attack_policy"]
    if policy == "all":
        return False, reach
    if policy == "never":
        return bool(great), []
    fight = fight_or_hide(s, memory, cfg, [threats[i] for i in great], able)[0] if great else False
    targets = [i for i in reach if not threats[i].get("great_danger") or fight]
    return bool(great) and not fight and not targets, targets


def danger_close(s: dict, cfg: dict) -> bool:
    """(0.105.26) A great danger or a besieger within shelter_hold_tiles of
    the nearest dwarf (the bridge's distance_to_nearest_dwarf: x/y, a level
    counting 3). One whose distance isn't known counts when it can reach."""
    lim = cfg.get("shelter_hold_tiles", 20)
    for t in _l(_d(s.get("others_on_map")).get("threats")):
        if not isinstance(t, dict) or not (t.get("great_danger") or t.get("invader")):
            continue
        d = t.get("distance_to_nearest_dwarf")
        if isinstance(d, (int, float)) and not isinstance(d, bool):
            if d <= lim:
                return True
        elif t.get("can_reach_dwarves"):
            return True
    return False


def _shelter_squads_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """While the AI hides, the squads hold the civilian alert's shelter
    (lua/ai-military.lua shelter); out again when the alert clears or the
    squads are sent to fight."""
    from planner_core import abs_tick, TICKS_PER_DAY
    squads = [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict) and q.get("id") is not None]
    hide, targets = hiding(s, memory, cfg)
    inside = [q for q in squads if q.get("sheltering")]
    # (0.105.22) a squad holds the shelter shelter_max_days at most, then
    # shelter_rest_days off to eat and drink: B (4 Nov) kept 7 squads on the
    # shelter order about two game years; 28 soldiers died of thirst where
    # they had killed the titan, 44 of the 49 hungry or parched were soldiers
    now = abs_tick(s)
    since = getattr(memory, "shelter_since", None) if memory is not None else None
    since = _d(since)
    rest = getattr(memory, "shelter_rest", None) if memory is not None else None
    rest = _d(rest)
    for q in inside:
        since.setdefault(str(q["id"]), now)
    for k in [k for k in since if k not in {str(q["id"]) for q in inside}]:
        del since[k]
    for k in [k for k, t in rest.items() if not isinstance(t, int) or t <= now]:
        del rest[k]
    if memory is not None:
        memory.shelter_since, memory.shelter_rest = since, rest
    # (0.105.26) ...but not mid-siege: the timer counts only while no great
    # danger or besieger is close (it let the squads out under the titan)
    close = danger_close(s, cfg)
    long_in = [] if close else [q for q in inside
                                if now - since.get(str(q["id"]), now) >= cfg["shelter_max_days"] * TICKS_PER_DAY]
    for q in long_in:
        proposals.append(Proposal("squad_recall", {"type": "squad_orders", "squad_id": q["id"], "clear": True},
                                  f"{q.get('name') or 'the squad'} has held the shelter {cfg['shelter_max_days']} "
                                  f"days: out for {cfg['shelter_rest_days']} to eat and drink", 1))
        rest[str(q["id"])] = now + cfg["shelter_rest_days"] * TICKS_PER_DAY
    # (0.105.24) a sheltered squad whose soldiers are thirsty or hungry (the
    # bridge's `parched`, ai-military members_state) is let out at once, as
    # the hospital burrow lets its thirsty out (0.105.22), and rests
    for q in inside:
        if q in long_in or not int(q.get("parched") or 0):
            continue
        proposals.append(Proposal("squad_recall", {"type": "squad_orders", "squad_id": q["id"], "clear": True},
                                  f"{q['parched']} soldier(s) of {q.get('name') or 'the squad'} in the shelter are "
                                  f"thirsty or hungry: out for {cfg['shelter_rest_days']} days to eat and drink", 1))
        rest[str(q["id"])] = now + cfg["shelter_rest_days"] * TICKS_PER_DAY
    # (0.105.26) a gate lost while the alarm is on: the shelter made again
    # over the fort as it is now (away from the entrance now open)
    stale = _d(s.get("military")).get("shelter_stale")
    if s.get("civ_alert") and isinstance(stale, int) and stale > 0:
        proposals.append(Proposal("shelter_refresh", {"type": "refresh_shelter"},
                                  f"{stale} entrance(s) shut when the shelter was made are open now (a gate lost): "
                                  "the shelter is made again away from them", 0))
    if hide:
        if not player_rules(s).get("squads_shelter", True):
            return
        if s.get("civ_alert_ready") is not True and not s.get("civ_alert"):
            return                       # no shelter burrow yet (the alarm rule sets one up)
        out = [q for q in squads if (q.get("members") or 0) > 0 and not q.get("sheltering")
               and str(q["id"]) not in rest and not int(q.get("parched") or 0)      # (0.105.24)
               and not (q.get("orders") or 0) > int(q.get("ai_orders") or 0)]
        if out:
            proposals.append(Proposal("shelter_squads", {"type": "shelter_squads", "squads": [q["id"] for q in out]},
                                      f"the dwarves hide from a great danger: {len(out)} squad(s) wait in the "
                                      "shelter with the civilians", 0))
        return
    # out once the alarm is over (sent to fight, the kill order replaces the
    # shelter order itself: _military_rules); the recall there does it too
    # when nothing can reach the dwarves any more
    if inside and not targets and not s.get("civ_alert") and reachable_threats(
            s, _d(_d(s.get("settings")).get("traits")), cfg):
        for q in inside:
            if q in long_in or int(q.get("parched") or 0):
                continue
            proposals.append(Proposal("squad_recall", {"type": "squad_orders", "squad_id": q["id"], "clear": True},
                                      f"the alarm is over: {q.get('name') or 'the squad'} leaves the shelter", 1))


def _gate_cut_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """An opening too wide to wall (or one refused for what stands in it) is
    cut where its open area leads down: hatches on the stairs down. The scan
    says which can be cut (`cut_hatches`) and why not (`cut_why`)."""
    rules_ = player_rules(s)
    ent = _d(s.get("entrances"))
    if not rules_["fortify_entrances"] or not ent.get("scanned") or "entrances" in s.get("_errors", {}):
        return
    from planner_core import abs_tick
    now = abs_tick(s)
    fails = getattr(memory, "gate_failures", None) or {}
    fail_ticks = getattr(memory, "gate_failure_ticks", None) or {}
    for e in _l(ent.get("entrances")):
        if not isinstance(e, dict) or e.get("sealed") or e.get("closing") or e.get("kind") != "surface":
            continue
        spot = f"{e.get('x')},{e.get('y')},{e.get('z')}"
        refused = spot in fails
        wide = (e.get("width") or 0) > cfg["fortify_max_width"]
        if not (wide or refused):
            continue
        # (0.105.0 review) a cut refused lately waits gate_retry_ticks, as a wall does
        when = fail_ticks.get("cut:" + spot)
        if "cut:" + spot in fails and isinstance(when, int) and 0 <= now - when < cfg["gate_retry_ticks"]:
            notes.append(f"the surface opening at x{e.get('x')} y{e.get('y')} couldn't be cut off below: "
                         f"{str(fails['cut:' + spot])[:160]} (tried again later)")
            continue
        from planner_military import _near_spot
        if _near_spot(e, getattr(memory, "gates_fortified", None) or {}):
            continue                  # cut (or walled) already: the next scan sees the hatches planned
        if isinstance(e.get("cut_hatches"), int) and e["cut_hatches"] > 0:
            proposals.append(Proposal("gate_cut", {"type": "cut_entrance", "entrance_id": e["id"]},
                                      f"the surface opening at x{e.get('x')} y{e.get('y')} is "
                                      + (f"{e.get('width')} wide" if wide else "refused a wall")
                                      + f": close the {e['cut_hatches']} stair(s) leading down from it with hatches, "
                                      "locked with the other gates", 5))
            return
        if wide and e.get("cut_why"):
            notes.append(f"the {e.get('width')}-wide surface opening at x{e.get('x')} y{e.get('y')} can't be cut "
                         f"off below either: {str(e['cut_why'])[:160]}")
