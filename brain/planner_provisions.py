"""(0.105.41, item 4) Provisions from the land: hunting, butchery and
tanning, fruit picked from trees, meals of more than one kind, and farms on
cavern soil.

The coverage audit's "should" list (12 Nov): the AI never sent a hunter
out, left the kills and hides to chance, never picked a tree's fruit,
cooked one kind of meal, and never farmed a cavern's soil (0.104.79 only
steered the crops).

The `provisions` report (lua/ai-provisions.lua) gives the game on the
surface and the hunters, DF's standing orders on butchering and tanning,
the bodies and hides waiting, the fruit trees near the fort and the
fruit-gathering zones, the meals by kind, and the AI's cavern plots.

  * hunting: a hunter or two (`hunters_max`) through the game's work detail
    while game walks the surface, crossbows and bolts are to spare after the
    crossbow squads' own, and no danger is about (`hunting_danger`: a threat
    that can reach the dwarves, invaders held off, a great danger, the
    alarm, a dangerous wild animal on the surface, a threat within
    `hunt_quiet_days`). Danger (or the Rules switch off): the AI's own
    hunters called in at once. The player's hunters are never touched.
  * butchery and tanning: DF's standing orders to butcher, tan and clean
    fish by themselves turned on when bodies, hides or raw fish wait (one the
    AI turned on that is off again is the player's: left off); a butcher and
    a tanner through the work details, their workshops when missing, a tan
    order for the hides lying about. Kills forbidden by "forbid other dead"
    are said, not unforbidden (dwarves would run out to them under fire).
  * fruit: a fruit-gathering zone over the densest stand of fruit trees near
    the fort when the fort has none, while the surface is safe; a gatherer
    while it stands and nobody gathers.
  * meal variety: with the store stocked, a few jobs of the kind of meal the
    store lacks when one kind is most of it (the welfare slider's -50 or
    lower never cooks lavish ones).
  * cavern farms: plots on a known cavern's soil near where the fort meets
    it, when the fort has underground seeds and nowhere else to sow them
    (a farm failure on record, or no underground plot while food or drink is
    short), no great beast is in the caverns and no hostile creature in that
    one (Rules switch `cavern_farms`).

Without a `provisions` section nothing here proposes or says anything.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (Proposal, TICKS_PER_DAY, MEAL_RECIPES, abs_tick, queued, _has_shop, _workshops_busy,
                          reachable_threats, held_off_threats, great_present, player_rules, food_per_dwarf,
                          is_ranged, _traits)

__all__ = ["provisions", "hunting_danger", "hunters_wanted", "meal_variety_pick", "cavern_target",
           "_provisions_rules", "MEAL_KIND_RECIPES"]

MEAL_KIND_RECIPES = {"biscuits": "prepare_easy_meal", "stew": "prepare_fine_meal", "roast": "prepare_lavish_meal"}
MEAL_INGREDIENTS = {"prepare_easy_meal": 2, "prepare_fine_meal": 3, "prepare_lavish_meal": 4}
FIXED_MODES = ("EverybodyDoesThis", "NobodyDoesThis")


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def provisions(s: dict) -> dict | None:
    """The bridge's provisions section, or None (an older bridge, a failed one)."""
    pv = s.get("provisions")
    if not isinstance(pv, dict) or not pv or "error" in pv or "provisions" in _d(s.get("_errors")):
        return None
    return pv


def _part(pv: dict, name: str) -> dict | None:
    p = pv.get(name)
    if not isinstance(p, dict) or "error" in p:
        return None
    return p


def hunting_danger(s: dict, memory, cfg: dict) -> str:
    """Why no dwarf should be out on the surface now ("" when it is safe)."""
    traits = _traits(s) if isinstance(s.get("settings"), dict) else {}
    if "others_on_map" in _d(s.get("_errors")):
        return "the creatures on the map could not be read"
    if reachable_threats(s, traits, cfg):
        return "a threat can reach the dwarves"
    if held_off_threats(s):
        return "invaders (or a danger on the surface) are held off at the gates"
    if great_present(s):
        return "a great danger is about"
    if memory is not None and getattr(memory, "ai_alert_raised", False):
        return "the AI's alarm is up"
    if s.get("civ_alert") is True:
        return "the civilian alert is on"
    pv = provisions(s)
    h = _part(pv, "hunting") if pv else None
    if h and _int(h.get("danger")) > 0:
        return f"{h['danger']} dangerous wild animal(s) on the surface"
    last = getattr(memory, "last_threat_tick", 0) if memory is not None else 0
    now = abs_tick(s)
    if last and isinstance(now, int) and 0 <= now - last < cfg["hunt_quiet_days"] * TICKS_PER_DAY:
        return f"a threat could reach the dwarves {(now - last) // TICKS_PER_DAY} day(s) ago"
    return ""


def hunters_wanted(s: dict, cfg: dict) -> tuple[int, str]:
    """Hunters the crossbows and bolts to spare allow (after the crossbow
    squads' own), at most `hunters_max`; and the limit in words."""
    g = _d(_d(s.get("military")).get("gear"))
    ranged = [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict) and is_ranged(q)]
    members = sum(_int(q.get("members")) for q in ranged)
    crossbows = _int(g.get("spare_crossbows")) - max(0, members - _int(g.get("ranged_armed")))
    bolts = _int(g.get("bolts")) - members * cfg["bolts_per_soldier"]
    n = max(0, min(cfg["hunters_max"], crossbows, bolts // max(1, cfg["hunt_bolts_per_hunter"])))
    why = f"{max(0, crossbows)} crossbow(s) and {max(0, bolts)} bolts to spare"
    return n, why


def _hunting_rule(s, pv, cfg, citizens, proposals, notes, memory, rules_) -> None:
    h = _part(pv, "hunting")
    if h is None:
        return
    ai = _int(h.get("ai_hunters"))
    danger = hunting_danger(s, memory, cfg)
    if not rules_["hunting"] or danger:
        if ai > 0:
            proposals.append(Proposal("hunting_stop", {"type": "hunters", "stop": True},
                                      (f"{danger}: " if danger else "hunting is off on the Rules tab: ")
                                      + f"call the AI's {ai} hunter(s) in", 1))
        return
    if citizens < cfg["hunt_min_citizens"] or _int(h.get("game")) < cfg["hunt_game_min"]:
        return
    if h.get("mode") in FIXED_MODES:
        return
    want, why = hunters_wanted(s, cfg)
    short = want - _int(h.get("hunters"))
    if short > 0:
        proposals.append(Proposal("hunting", {"type": "hunters", "count": short},
                                  f"{h.get('game')} wild animal(s) to hunt on the surface, {why} and no danger "
                                  f"about: put {short} hunter(s) on it (called in when danger comes)", 6))


def _butchery_rule(s, pv, cfg, citizens, proposals, notes, memory) -> None:
    b = _part(pv, "butchery")
    if b is None:
        return
    st, ai = _d(b.get("standing")), _d(b.get("ai_set"))
    corpses, hides = _int(b.get("corpses")), _int(b.get("hides"))
    raw_fish = _int(_d(s.get("stocks")).get("raw_fish"))
    blds = _d(s.get("buildings"))
    on = {}
    for name, waiting in (("auto_butcher", corpses), ("auto_tan", hides), ("auto_fishery", raw_fish)):
        # 0 is off; one the AI turned on and is off again is the player's
        if waiting > 0 and st.get(name) == 0 and ai.get(name) != 1:
            on[name] = 1
    if on:
        proposals.append(Proposal("food_standing", {"type": "food_standing", "orders": on},
                                  f"{corpses} bodies to butcher, {hides} hides to tan, {raw_fish} raw fish: let the "
                                  + " and the ".join({"auto_butcher": "butchers", "auto_tan": "tanners",
                                                      "auto_fishery": "fishery"}[k] for k in sorted(on))
                                  + " work by themselves (DF's standing orders)", 5))
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    if corpses >= cfg["butcher_corpses_min"]:
        if not _has_shop(blds, "Butchers"):
            if corpses >= cfg["butcher_shop_corpses"] and not _workshops_busy(open_):
                proposals.append(Proposal("butchery_shop", {"type": "start_project", "kind": "workshops",
                                                            "shops": ["Butchers"]},
                                          f"{corpses} bodies wait to be butchered and the fort has no butcher's "
                                          "shop: build one", 5))
        elif _int(b.get("butchers")) == 0:
            proposals.append(Proposal("butchery_labor", {"type": "assign_labor", "job": "BUTCHER", "count": 1},
                                      f"{corpses} bodies wait at the butcher's and nobody butchers: put a "
                                      "dwarf on it", 4))
    if hides >= cfg["tan_hides_min"]:
        if not _has_shop(blds, "Tanners"):
            if not _workshops_busy(open_) and not any(p.rule == "butchery_shop" for p in proposals):
                proposals.append(Proposal("butchery_shop", {"type": "start_project", "kind": "workshops",
                                                            "shops": ["Tanners"]},
                                          f"{hides} raw hides lie about and the fort has no tanner's: build one "
                                          "(leather for bags, armour and the moods)", 6))
        elif _int(b.get("tanners")) == 0:
            proposals.append(Proposal("butchery_labor", {"type": "assign_labor", "job": "TANNER", "count": 1},
                                      f"{hides} raw hides lie about and nobody tans: put a dwarf on it", 5))
        elif not queued(s, {"tan_hide"}):
            n = min(hides, cfg["tan_order_max"])
            proposals.append(Proposal("tanning", {"type": "work_order", "recipe": "tan_hide", "amount": n},
                                      f"{hides} raw hides lie about (they rot): tan {n}", 5, True))
    if _int(b.get("corpses_forbidden")) >= cfg["butcher_shop_corpses"] and st.get("forbid_other_nohunt") == 1:
        notes.append(f"{b['corpses_forbidden']} kills lie forbidden (DF's \"forbid other dead\" standing order): "
                     "left so, the AI never sends dwarves out to them; unforbid them if the ground is safe")


def _fruit_rule(s, pv, cfg, citizens, proposals, notes, memory) -> None:
    f = _part(pv, "fruit")
    if f is None:
        return
    lb = _d(_d(s.get("labor")).get("jobs"))
    g = _d(lb.get("gathering"))
    if _int(f.get("zones")) > 0:
        if (_int(f.get("ai_zones")) > 0 and _int(g.get("doing")) == 0 and _int(g.get("candidates")) > 0
                and g.get("mode") not in FIXED_MODES):
            n = cfg["fruit_pickers"]
            proposals.append(Proposal("fruit_pickers", {"type": "assign_labor", "job": "gathering", "count": n},
                                      f"the fruit trees near the fort are zoned for picking and nobody gathers: "
                                      f"put {n} dwarf(s) on it", 6))
        return
    if citizens < cfg["fruit_min_citizens"] or _int(f.get("trees")) < cfg["fruit_trees_min"]:
        return
    if hunting_danger(s, memory, cfg):
        return
    proposals.append(Proposal("fruit_zone", {"type": "fruit_zone", "min_trees": cfg["fruit_stand_min"]},
                              f"{f.get('trees')} fruit trees near the fort and nobody picks them: zone the "
                              "densest stand for fruit gathering (food, and fruit to brew)", 6))


def meal_variety_pick(by_kind: dict, welfare: float, cfg: dict) -> tuple[str, str] | None:
    """(kind, recipe) of the meal to cook for variety, or None: one kind is
    `meal_variety_share` of the servings and another under `meal_variety_low`
    (the scarcest of those; lavish ones only above welfare -50)."""
    by = {k: _int(by_kind.get(k)) for k in MEAL_KIND_RECIPES}
    total = sum(by.values())
    if total <= 0 or max(by.values()) < total * cfg["meal_variety_share"]:
        return None
    kinds = [k for k in ("biscuits", "stew", "roast") if not (k == "roast" and welfare <= -50)]
    low = [k for k in kinds if by[k] < total * cfg["meal_variety_low"]]
    if not low:
        return None
    k = min(low, key=lambda x: (by[x], kinds.index(x)))
    return k, MEAL_KIND_RECIPES[k]


def _meal_variety_rule(s, pv, cfg, citizens, proposals, notes, memory) -> None:
    m = _part(pv, "meals")
    if m is None or not _has_shop(_d(s.get("buildings")), "Kitchen"):
        return
    by = _d(m.get("by_kind"))
    total = sum(_int(by.get(k)) for k in MEAL_KIND_RECIPES)
    if total < max(1, citizens) * cfg["meal_variety_min_pd"] or queued(s, MEAL_RECIPES):
        return
    welfare = _traits(s).get("welfare", 0) if isinstance(s.get("settings"), dict) else 0
    pick = meal_variety_pick(by, welfare or 0, cfg)
    if pick is None:
        return
    kind, recipe = pick
    jobs = cfg["meal_variety_jobs"]
    stacks = _d(s.get("supplies")).get("food_stacks")
    if isinstance(stacks, int) and not isinstance(stacks, bool):
        jobs = min(jobs, stacks // MEAL_INGREDIENTS[recipe])
    if jobs < 1:
        return
    top = max(MEAL_KIND_RECIPES, key=lambda k: _int(by.get(k)))
    proposals.append(Proposal("meal_variety", {"type": "work_order", "recipe": recipe, "amount": jobs},
                              f"{_int(by.get(top))} of the {total} servings are {top} and {_int(by.get(kind))} "
                              f"{kind}: cook {jobs} job(s) of {kind} so the meals aren't all one kind", 6, True))


def cavern_target(s: dict, cfg: dict) -> dict | None:
    """The cavern to farm and where the fort meets it ({name, at}), or None:
    a known cavern open to the fort's ground, no great beast in the caverns,
    no hostile creature or threat in that cavern, its way down not sealed
    (fix3: a locked door or hatch on its column, or the seal's record)."""
    from planner_threats import cavern_great, deep_read, ALL_CAVERNS
    if not deep_read(s) or cavern_great(s):
        return None
    sealed = _d(_d(s.get("threats")).get("sealed"))
    if ALL_CAVERNS in sealed:
        return None
    o = _d(s.get("others_on_map"))
    busy = {str(w.get("layer")) for w in _l(o.get("wild_hostile")) if isinstance(w, dict)}
    busy |= {str(t.get("layer")) for t in _l(o.get("threats")) if isinstance(t, dict)}
    for c in _l(_d(s.get("deep")).get("caverns")):
        if not isinstance(c, dict) or not (c.get("discovered") and c.get("open")):
            continue
        if str(c.get("name")) in busy or str(c.get("name")) in sealed:
            continue
        # (fix3) a locked door or hatch on the way down: the farmers couldn't
        # pass (a door reads closed whenever nobody walks through: only the lock counts)
        if any(isinstance(col, dict) and col.get("building") in ("Door", "Hatch") and col.get("locked")
               for col in _l(c.get("column"))):
            continue
        at = None
        for j in _l(c.get("junctions")):
            cave = _d(_d(j).get("cave"))
            if all(isinstance(cave.get(k), int) for k in "xyz"):
                at = {k: cave[k] for k in "xyz"}
                break
        oa = _d(c.get("open_at"))
        if at is None and all(isinstance(oa.get(k), int) for k in "xyz"):
            at = {k: oa[k] for k in "xyz"}
        if at is not None:
            return {"name": c.get("name"), "at": at}
    return None


def _cavern_farm_rule(s, pv, cfg, citizens, proposals, notes, memory, rules_) -> None:
    cv = _part(pv, "cavern")
    if cv is None or not rules_["cavern_farms"]:
        return
    have = _int(cv.get("tiles"))
    if have >= cfg["cavern_farm_max_tiles"]:
        return
    fm = _d(s.get("farms"))
    crops = [v for v in _d(fm.get("crops")).values() if isinstance(v, dict)]
    seeds = sum(_int(v.get("seeds")) for v in crops if v.get("underground") and _l(v.get("seasons")))
    if seeds < cfg["seeds_per_plot"]:
        return
    from planner_farms import farm_plots_live, drink_known_short
    under = sum(_int(p.get("tiles")) for p in farm_plots_live(s) if p.get("underground") and not p.get("dead"))
    short = food_per_dwarf(s) < cfg["found_food_per_dwarf"] or drink_known_short(s, cfg)
    failed = bool(getattr(memory, "farm_failure", "")) if memory is not None else False
    if not (failed or (under == 0 and short)):
        return
    traits = _traits(s) if isinstance(s.get("settings"), dict) else {}
    if reachable_threats(s, traits, cfg) or great_present(s):
        return
    tgt = cavern_target(s, cfg)
    if tgt is None:
        return
    n = min(cfg["cavern_farm_tiles"], seeds, cfg["cavern_farm_max_tiles"] - have)
    if n < 4:
        return
    why = (f"the farms found no soil: {memory.farm_failure}" if failed
           else f"no underground plot and {'food' if food_per_dwarf(s) < cfg['found_food_per_dwarf'] else 'drink'} "
                "is short")
    proposals.append(Proposal("cavern_farm", {"type": "cavern_farm", "at": tgt["at"], "tiles": n},
                              f"{seeds} seeds of underground crops and {why}: lay out {n} tiles of plots on "
                              f"{tgt['name']}'s soil near where the fort meets it (no beast in the caverns)", 5))


def _provisions_rules(s: dict, cfg: dict, citizens: int, proposals: list, notes: list, memory=None) -> None:
    """Every provisions rule, each on its own part of the section."""
    pv = provisions(s)
    if pv is None:
        return
    rules_ = player_rules(s)
    for fn in (_hunting_rule, _cavern_farm_rule):
        try:
            fn(s, pv, cfg, citizens, proposals, notes, memory, rules_)
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            notes.append(f"provisions: {fn.__name__} skipped ({type(e).__name__}: {e})")
    for fn in (_butchery_rule, _fruit_rule, _meal_variety_rule):
        try:
            fn(s, pv, cfg, citizens, proposals, notes, memory)
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            notes.append(f"provisions: {fn.__name__} skipped ({type(e).__name__}: {e})")
