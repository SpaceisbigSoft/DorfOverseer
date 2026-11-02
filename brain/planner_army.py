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
from planner_core import (AGENDA_THEMES, Proposal, all_clear, ask_player, is_ranged, player_rules, queued,
                          reachable_threats, _has_shop)

__all__ = ["_army_gear_rule", "_quiver_rule", "_bolts_rule", "_shelter_squads_rule", "_gate_cut_rule",
           "hiding", "WEAPON_RECIPES"]

AGENDA_THEMES.update({"gear_fix": "arm the soldiers", "quivers": "quivers for the crossbows",
                      "bolts": "bolts for the crossbows", "shelter_squads": "the squads hide with the civilians",
                      "gate_cut": "close the wide openings"})

# the weapon an entry names, and how the fort makes it
WEAPON_RECIPES = {"ITEM_WEAPON_AXE_BATTLE": "metal_battle_axe", "ITEM_WEAPON_SPEAR": "metal_spear",
                  "ITEM_WEAPON_MACE": "metal_mace", "ITEM_WEAPON_CROSSBOW": "wooden_crossbow"}

# reasons the AI mends itself (lua/ai-military.lua fix_gear_gaps)
FIXABLE = ("stale on a soldier's list", "wrong material", "fillable")


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
    shields = bool(spare_shields > 0 and int(sh.get("no_entry") or 0) > 0 and metal_melee)
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
        ask_player(notes, f"{why['unreachable']} soldier(s) can't get to the free weapons (behind a closed door "
                   "or outside the gates): open the way or haul them in")
    if why.get("forbidden, dumped or to melt"):
        notes.append(f"{why['forbidden, dumped or to melt']} weapon place(s) wait on weapons that are forbidden, "
                     "dumped or set to melt")


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
    able = [q for q in squads if (q.get("members") or 0) >= cfg["min_squad_to_fight"]]
    great = [i for i in reach if threats[i].get("great_danger")]
    policy = rules_["attack_policy"]
    if policy == "all":
        return False, reach
    if policy == "never":
        return bool(great), []
    fight = fight_or_hide(s, memory, cfg, [threats[i] for i in great], able)[0] if great else False
    targets = [i for i in reach if not threats[i].get("great_danger") or fight]
    return bool(great) and not fight and not targets, targets


def _shelter_squads_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """While the AI hides, the squads hold the civilian alert's shelter
    (lua/ai-military.lua shelter); out again when the alert clears or the
    squads are sent to fight."""
    squads = [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict) and q.get("id") is not None]
    hide, targets = hiding(s, memory, cfg)
    inside = [q for q in squads if q.get("sheltering")]
    if hide:
        if not player_rules(s).get("squads_shelter", True):
            return
        if s.get("civ_alert_ready") is not True and not s.get("civ_alert"):
            return                       # no shelter burrow yet (the alarm rule sets one up)
        out = [q for q in squads if (q.get("members") or 0) > 0 and not q.get("sheltering")
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
    for e in _l(ent.get("entrances")):
        if not isinstance(e, dict) or e.get("sealed") or e.get("closing") or e.get("kind") != "surface":
            continue
        spot = f"{e.get('x')},{e.get('y')},{e.get('z')}"
        refused = spot in (getattr(memory, "gate_failures", None) or {})
        wide = (e.get("width") or 0) > cfg["fortify_max_width"]
        if not (wide or refused):
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
