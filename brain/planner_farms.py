"""planner_farms: drink, farms and food (split out of planner_industry in
0.105.25, 13c): the drink target and the crisis's drinking, the brew jobs
open, the crops (autofarm's thresholds, or the plots set by the AI), the
farm plots wanted, the kitchen's ban on brewables, fishing, milk, cheese and
eggs. planner_industry re-exports every name here."""

from __future__ import annotations

import math
from culture import layout_style, new_history, profile_from
from digest import _d, _l
from planner_core import *  # noqa: F401,F403

__all__ = ["drink_short", "_crop_rules", "farm_plots_live", "crops_owned", "drink_known_short", "_farm_crops_rule", "_kitchen_rule", "_fishery_rule", "_dairy_rule", "_eggs_rule", "drink_below_target", "drink_crisis", "drink_target_per_dwarf", "crisis_brew_room", "brew_jobs_open", "farm_target", "thirsty_farm_extra", "_farm_rule", "drink_swap_wanted"]


def drink_short(s: dict, cfg: dict) -> bool:
    """(0.99.6) Under the urgent drink line and little a still can brew."""
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    drink = int(_d(s.get("stocks")).get("drink") or 0)
    sup = _d(s.get("supplies"))
    brewable = int(sup.get("brewable_plants") or 0) + int(sup.get("brewable_growths") or 0)
    return drink < citizens * cfg["urgent_drink_per_dwarf"] and brewable < citizens


def _crop_rules(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(0.99.6) Crops for drink: while drink is short, autofarm's thresholds
    favour the crops a still can brew (the fort has seeds of) and hold back
    the rest; put back to autofarm's default once drink has recovered.
    region2: 18 of 151 plants brewable, drink 42 for 243 dwarves."""
    if memory is None:
        return
    farms = _d(s.get("farms"))
    crops = {k: v for k, v in _d(farms.get("crops")).items() if isinstance(v, dict)}
    if not crops or not has_farms(s):
        return
    if crops_owned(s, memory) or memory.farm_crops_player:
        # (0.105.7 review) the AI sets the plots itself (autofarm off), or the
        # player took them back: autofarm's thresholds would switch it on
        # again (act_farm_thresholds enables it) in the very cycle
        # set_farm_crops switched it off
        return
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    drink = int(_d(s.get("stocks")).get("drink") or 0)
    # crops a plot can grow: seeds in stock and a season (trees have none)
    seeded = {k: v for k, v in crops.items() if int(v.get("seeds") or 0) > 0
              and (v.get("seasons") is None or _l(v.get("seasons")))}
    brew = sorted(k for k, v in seeded.items() if v.get("brews"))
    if drink_short(s, cfg):
        # (0.99.6) region2: 10 plots, all underground, nothing planted (25
        # plump helmet seeds, 3 cave wheat) while 500+ seeds of brewable
        # surface crops waited: plots on the surface's soil for them
        under_brew = sum(int(v.get("seeds") or 0) for k, v in seeded.items() if v.get("brews") and v.get("underground"))
        surface_brew = sum(int(v.get("seeds") or 0) for k, v in seeded.items()
                           if v.get("brews") and not v.get("underground"))
        plots_under = int(farms.get("plots_underground") or 0)
        if (int(farms.get("plots_surface") or 0) == 0 and surface_brew >= cfg["surface_farm_seeds"]
                and under_brew < plots_under * cfg["seeds_per_plot"]):
            n = min(cfg["surface_farm_tiles"], surface_brew)
            proposals.append(Proposal("surface_farm", {"type": "farm_plots", "tiles": n, "dig": False, "outside": True},
                                      f"drink is short ({drink} for {citizens}): the {plots_under} plots are "
                                      f"underground with {under_brew} seeds of underground crops to brew, and "
                                      f"{surface_brew} seeds of surface crops wait: lay out {n} tiles of plots "
                                      "on the surface's soil for them", 2))
        if not brew:
            ask_player(notes, f"drink is short ({drink} for {citizens}) and the fort has no seeds of a crop a "
                       "still can brew: buy seeds or brewable plants from a caravan (the dwarves gather shrubs "
                       "meanwhile)")
            return
        if memory.farm_steer in ("drink", "crops"):     # (0.105.5) "crops": set_farm_crops sets the plots itself
            notes.append("the farms grow brewable crops while drink is short: " + ", ".join(
                f"{_d(crops[k]).get('name') or k.lower()} ({crops[k].get('seeds')} seeds)" for k in brew[:4]))
            return
        th = {k: cfg["crop_brew_threshold"] for k in brew}
        th.update({k: cfg["crop_other_threshold"] for k in seeded if k not in th})
        proposals.append(Proposal("crops", {"type": "farm_thresholds", "thresholds": th, "steer": "drink"},
                                  f"drink is short ({drink} for {citizens}): farm the crops a still can brew ("
                                  + ", ".join(_d(crops[k]).get("name") or k.lower() for k in brew[:4])
                                  + ") ahead of the rest (autofarm's thresholds)", 2))
    elif memory.farm_steer == "drink" and drink >= citizens * cfg["drink_recovered_per_dwarf"]:
        th = {k: cfg["crop_default_threshold"] for k in seeded}
        if th:
            proposals.append(Proposal("crops", {"type": "farm_thresholds", "thresholds": th, "steer": ""},
                                      f"drink has recovered ({drink} for {citizens}): the farms go back to "
                                      "autofarm's own choice of crops", 5))
    else:
        # (0.104.79) plots left fallow: autofarm plants a crop only while its
        # stock is under the threshold, and its default (50) is a small fort's
        # (Enxah, 88 dwarves: 12 plots, none planted this season, 131 plump
        # helmet seeds, 73 in stock, the stills short of plants for the
        # winter's drink): thresholds that grow with the fort, more for the
        # brewable crops
        plots = int(farms.get("plots") or farms.get("built") or 0)
        planted = sum(int(v.get("planted") or 0) for v in crops.values())
        # (0.105.5) not once the AI sets the plots' crops itself (autofarm is off)
        if plots and planted * 2 < plots and seeded and memory.farm_steer not in ("pop", "crops"):
            th = {k: max(cfg["crop_default_threshold"], citizens * cfg["crop_per_dwarf"]) for k in seeded}
            th.update({k: max(cfg["crop_default_threshold"], citizens * cfg["crop_brew_per_dwarf"]) for k in brew})
            proposals.append(Proposal("crops", {"type": "farm_thresholds", "thresholds": th, "steer": "pop"},
                                      f"{plots - planted} of {plots} farm plots lie fallow this season (autofarm's "
                                      f"thresholds are a small fort's): keep more of each crop for {citizens} "
                                      "dwarves, the brewable ones most", 4))


def farm_plots_live(s: dict) -> list:
    """(0.105.5) The report's plots one by one (a bridge from 0.105.5 on;
    an older one: [])."""
    return [p for p in _l(_d(s.get("farms")).get("plot_list")) if isinstance(p, dict)]


def crops_owned(s: dict, memory) -> bool:
    """(0.105.7 review) The AI sets the plots' crops now (autofarm off): it
    did, the player hasn't taken them back, and the report still lists the
    plots with one that can grow something. Else autofarm is the fallback
    (an old bridge or a failed plot list, or only dead plots: no crop logic
    at all otherwise)."""
    if memory is None or getattr(memory, "farm_steer", "") != "crops" or getattr(memory, "farm_crops_player", False):
        return False
    return any(not p.get("dead") for p in farm_plots_live(s))


def drink_known_short(s: dict, cfg: dict) -> bool:
    """(0.105.7 review) Drink under the urgent line, read from the report: a
    missing stocks section (or count) is not "0 drink"."""
    if "stocks" in _d(s).get("_errors", {}) or not isinstance(_d(s.get("stocks")).get("drink"), (int, float)):
        return False
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    return s["stocks"]["drink"] < citizens * cfg["urgent_drink_per_dwarf"]


def _farm_crops_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(0.105.5) Hammerstirred (2 Nov): six forts' plots lay fallow all year
    with autofarm on (fort B: 4 of 5 fallow, drink 0-11 for 7 dwarves, 147
    seeds; fort E: 4 of 4, drink 9 for 10, 162 seeds). The AI sets each
    plot's crop itself (set_farm_crops: every season where a crop the fort
    has seeds of grows there, brewable first while drink is short) when a
    plot that could grow something lies fallow or holds a crop that can't
    grow there; plots where nothing the fort has grows are said, once."""
    if memory is None:
        return
    plots = farm_plots_live(s)
    if not plots:
        return
    if memory.farm_crops_player:
        # (0.105.7 review) the player switched autofarm back on: theirs
        return
    fm = _d(s.get("farms"))
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    drink = int(_d(s.get("stocks")).get("drink") or 0)
    # (0.105.7 review) unknown drink (a failed stocks section) isn't short:
    # it read as 0 and made the rule urgent
    short = drink_known_short(s, cfg)
    dead = [p for p in plots if p.get("dead")]
    # (0.105.7 review) said once a season, not every cycle
    season_key = f"{_d(s.get('date')).get('year')}-{_d(s.get('date')).get('season')}"
    if dead and memory.farm_dead_noted != season_key:
        memory.farm_dead_noted = season_key
        where = "surface" if all(not p.get("underground") for p in dead) else "farm"
        notes.append(f"{len(dead)} {where} plot(s) can grow nothing the fort has seeds of, in any season "
                     "(DF offers only \"Leave fallow\"): underground crops need underground plots")
    idle = [p for p in plots if not p.get("dead") and int(p.get("options") or 0) > 0
            and (p.get("fallow") or not p.get("ok_now"))]
    # the AI hasn't set the crops yet: the later seasons too (autofarm sets only the current one)
    unset = memory.farm_steer != "crops" and any(not p.get("dead") for p in plots)
    # (0.105.33 B4) drink short and the AI's own plots all sown with crops a
    # still can't brew: the bridge swaps them for brewable ones only when
    # asked with drink, and nothing else asked
    swap = short and memory.farm_steer == "crops" and drink_swap_wanted(s, plots)
    if not idle and not unset and not swap:
        return
    action = {"type": "set_farm_crops", "drink": short}
    if not thread_plants_here(s) and any(_d(c).get("thread") and int(_d(c).get("seeds") or 0) > 0
                                         for c in _d(fm.get("crops")).values()):
        action["thread"] = True
    why = (f"{len(idle)} of {len(plots)} farm plot(s) lie fallow (or hold a crop that can't grow there) "
           "while the fort has seeds that grow there" if idle else
           f"the {len(plots)} farm plot(s) get a crop for every season the fort's seeds grow in" if unset else
           "the AI's farm plots grow crops a still can't brew while a brewable crop the fort has seeds of "
           "could grow there")
    proposals.append(Proposal("farm_crops", action,
                              why + (f": brewable crops first, drink is short ({drink} for {citizens})"
                                     if short else ": set each plot's crop (autofarm off)"),
                              1 if short and idle else 2 if swap else 4))


CROP_SEASONS = ("spring", "summer", "autumn", "winter")


def drink_swap_wanted(s: dict, plots: list) -> bool:
    """(0.105.33 B4) A live plot grows, this season, a crop the AI set that a
    still can't brew, while a brewable crop the fort has seeds of grows there
    this season (underground crops underground, the rest on the surface).
    From the plots' crops when the report gives them (and, from 0.105.33,
    whether the AI set them: ai_now), else from the crops sown this season."""
    fm = _d(s.get("farms"))
    crops = {k: v for k, v in _d(fm.get("crops")).items() if isinstance(v, dict)}
    season = str(fm.get("season") or _d(s.get("date")).get("season") or "")
    def grows_now(c: dict) -> bool:
        ss = c.get("seasons")
        return ss is None or season in _l(ss)
    def brew_for(under) -> bool:
        return any(c.get("brews") and int(c.get("seeds") or 0) > 0 and grows_now(c)
                   and bool(c.get("underground")) == bool(under) for c in crops.values())
    live = [p for p in plots if not p.get("dead")]
    seen = False
    if season in CROP_SEASONS:
        i = CROP_SEASONS.index(season)
        for p in live:
            pc = p.get("crops")
            if not isinstance(pc, list) or len(pc) <= i:
                continue
            seen = True
            c = crops.get(pc[i])
            if (c is not None and not c.get("brews") and p.get("ai_now") is not False
                    and brew_for(p.get("underground"))):
                return True
    if seen:
        return False
    # an older report (no crops per plot): a crop that doesn't brew is sown
    return any(not c.get("brews") and int(c.get("planted") or 0) > 0 and brew_for(c.get("underground"))
               for c in crops.values())


def _kitchen_rule(s: dict, memory, cfg: dict, proposals: list) -> None:
    """(0.100) Cooking eats brewable plants and fruit and keeps no seed
    (brewing keeps it): while drink is short the kitchen may not cook them;
    the ban is lifted once drink has recovered (only the AI's own bans)."""
    if memory is None:
        return
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    st = _d(s.get("stocks"))
    drink = int(st.get("drink") or 0)
    # (0.105.16) meals to spare and drink under its target: cooking a brewable
    # plant adds a meal nobody needs and takes a drink away (B, the Monastery:
    # the ban lifted at 198 drink for 46 with 2,802 meals in store, 62 a dwarf)
    meals = int(st.get("prepared_meals") or 0)
    # (0.105.17) a ban kept for spare meals lifts only 20% over the target (B
    # flipped it at 305 and 315 drink for 44, a target of ~308)
    margin = 1.2 if memory.kitchen_ban else 1.0
    spare_meals = (meals >= citizens * cfg["meals_per_dwarf"] * cfg.get("kitchen_ban_meals_factor", 3)
                   and drink < citizens * cfg["drink_per_dwarf"] * margin)
    if (drink_short(s, cfg) or spare_meals) and not memory.kitchen_ban:
        why = (f"drink is short ({drink} for {citizens})" if drink_short(s, cfg) else
               f"drink is under its target ({drink} for {citizens}) and the fort has meals to spare ({meals})")
        proposals.append(Proposal("kitchen", {"type": "kitchen_brewables", "ban": True},
                                  f"{why}: the kitchen stops cooking the "
                                  "plants and fruit a still can brew (cooking keeps no seed)", 2))
    elif memory.kitchen_ban and not spare_meals and drink >= citizens * cfg["drink_recovered_per_dwarf"]:
        proposals.append(Proposal("kitchen", {"type": "kitchen_brewables", "ban": False},
                                  f"drink has recovered ({drink} for {citizens}): the kitchen may cook "
                                  "brewable plants again", 5))


def _fishery_rule(s: dict, cfg: dict, proposals: list) -> None:
    """(0.99.4) Raw fish piling up and no fishery to clean them: only a young
    fort got one (region2: 7940 raw fish at 228 dwarves, meals for the
    lavish cooks cancelled for want of meat or fish)."""
    b = _d(s.get("buildings"))
    if _has_shop(b, "Fishery") or int(_d(s.get("stocks")).get("raw_fish") or 0) < cfg["fishery_raw_fish"]:
        return
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    if _workshops_busy(open_):
        return
    n = int(_d(s.get("stocks")).get("raw_fish") or 0)
    for p in proposals:                    # one workshops level: join the still or kitchen's
        if p.rule == "bottleneck" and p.action.get("kind") == "workshops":
            p.action["shops"] = list(p.action.get("shops") or []) + ["Fishery"]
            p.reason += f"; and a fishery for {n} raw fish"
            p.priority = min(p.priority, 3)
            return
    proposals.append(Proposal("fishery", {"type": "start_project", "kind": "workshops", "shops": ["Fishery"]},
                              f"{n} raw fish and no fishery to clean them for the kitchen: build one", 3))


def _dairy_rule(s: dict, cfg: dict, citizens: int, proposals: list) -> None:
    """(0.104.79) Milk and cheese: the tame cows, goats and the like milked at
    the farmer's workshop, their milk made into cheese there. Cheese is a
    cook's ingredient of more worth than fish and plants (Enxah: no cheese,
    no eggs, 28 dwarves wanting a good meal and 27 good meals for 88), and it
    keeps. Up to `dairy_batch` at a time while the cheese kept is under
    `cheese_per_dwarf` a dwarf; a Beast-friends fort still milks (no harm)."""
    if young_fort(s, cfg) or not _has_shop(s["buildings"], "Farmers"):
        return
    sup, st = _d(s.get("supplies")), _d(s.get("stocks"))
    milkable, milk = int(sup.get("milkable") or 0), int(sup.get("milk") or 0)
    cheese = int(st.get("cheese") or 0)
    if cheese >= citizens * cfg["cheese_per_dwarf"]:
        return
    if milk > 0 and not queued(s, {"make_cheese"}):
        proposals.append(Proposal("dairy", {"type": "work_order", "recipe": "make_cheese",
                                            "amount": min(cfg["dairy_batch"], milk)},
                                  f"{milk} milk and {cheese} cheese for {citizens} dwarves: make cheese "
                                  "(it lifts the meals and keeps)", 6, True))
    elif milkable > 0 and milk == 0 and not queued(s, {"milk_creature"}):
        proposals.append(Proposal("dairy", {"type": "work_order", "recipe": "milk_creature",
                                            "amount": min(cfg["dairy_batch"], milkable)},
                                  f"{milkable} tame animals give milk and the fort has no cheese: milk them "
                                  "(for cheese)", 6, True))


def _eggs_rule(s: dict, cfg: dict, proposals: list) -> None:
    """(0.104.80) Eggs: a hen lays only in a nest box (DF wiki, Nest box);
    Enxah had none. Stone nest boxes are ordered at the mason's while fewer
    are built or free than hens (up to `nest_box_max`), and the bridge pens
    the loose hens and plans the boxes in their pasture."""
    if young_fort(s, cfg):
        return
    sup = _d(s.get("supplies"))
    hens = int(sup.get("egg_layers") or 0)
    if hens < 2:
        return
    want = min(hens, cfg["nest_box_max"])
    built, free = int(sup.get("nest_boxes") or 0), int(sup.get("nest_box_items") or 0)
    if built >= want:
        return
    short = want - built - free - queued(s, {"stone_nest_box"})
    if short > 0 and _has_shop(s["buildings"], "Masons"):
        proposals.append(Proposal("nest_box_order", {"type": "work_order", "recipe": "stone_nest_box",
                                                     "amount": min(5, short)},
                                  f"{hens} hens and {built} nest boxes: make stone nest boxes (hens lay only in one)",
                                  5, True))
    loose = hens - int(sup.get("egg_layers_penned") or 0)
    if free > 0 or loose > 0:
        proposals.append(Proposal("eggs", {"type": "nest_boxes", "max": 3},
                                  f"{hens} hens, {built} nest boxes built, {free} free"
                                  + (f", {loose} hens in no pasture" if loose else "")
                                  + ": pen the hens together and put nest boxes in their pasture (for eggs)", 5))


def drink_below_target(s: dict, citizens: int, cfg: dict, memory=None) -> bool:
    """(0.102.2) Drink under the fort's own target per dwarf ((0.104.169) the
    crisis's higher target while the fort is in crisis, given the memory)."""
    drink = _d(s.get("stocks")).get("drink")
    return isinstance(drink, (int, float)) and citizens > 0 and drink < citizens * drink_target_per_dwarf(s, memory, cfg)


def drink_crisis(s: dict, memory, cfg: dict) -> bool:
    """(0.104.169) Drink is a crisis lever: the fort is in crisis (crisis.py's
    memory.crisis) and its food isn't thin. Being drunk was by far the fort's
    biggest relief (Teacheroar: inebriation eased -1932 stress across 149
    citizens, the next relief -130) while drink ran under its target. Food
    under the floor wins: the stills' plants are food too."""
    c = getattr(memory, "crisis", None)
    if not (isinstance(c, dict) and c.get("since") and c.get("why")):
        return False
    return food_per_dwarf(s) >= cfg["crisis_drink_food_floor_per_dwarf"]


def drink_target_per_dwarf(s: dict, memory, cfg: dict) -> float:
    """(0.104.169) The drink kept per dwarf: `drink_per_dwarf`, x
    `crisis_drink_share` while drink is a crisis lever."""
    base = float(cfg["drink_per_dwarf"])
    return base * cfg["crisis_drink_share"] if memory is not None and drink_crisis(s, memory, cfg) else base


def crisis_brew_room(s: dict, recipe: str) -> bool:
    """(0.104.169) In a crisis, may the next batch of `recipe` be queued while
    the AI's order of it is still open? Only once the open orders' remaining
    work is all on the stills: every job still to do made (amount_left no
    more than the jobs it has made), so the next batch only waits for a still
    coming free and no copy waits long enough to look stuck.
    (review) DF 53 counts a manager order's amount_left down as its jobs
    FINISH, not as they are made: Teacheroar's live orders all read
    amount_left == amount_total with jobs made and worked (brew_drink 10/10
    with 6 jobs on the stills, stone_crafts 10/10 with 10 made, plaster 1/1
    with its one job worked), so a made job is still in amount_left."""
    for o in _l(s.get("orders")):
        if isinstance(o, dict) and o.get("by_ai") and o.get("recipe") == recipe:
            made = int(_d(o.get("jobs")).get("n") or 0)
            if int(o.get("amount_left") or 0) > made:
                return False
    return True


def brew_jobs_open(s: dict) -> int:
    """(0.104.169, review) The brew jobs the AI's open brew orders have still
    to finish (amount_left: made or not, see crisis_brew_room): each wants an
    empty barrel or pot, so a further brew order is sized by what is left."""
    return sum(max(0, int(o.get("amount_left") or 0)) for o in _l(s.get("orders"))
               if isinstance(o, dict) and o.get("by_ai") and o.get("recipe") in BREW_RECIPES)


def farm_target(s: dict, traits: dict, citizens: int, cfg: dict) -> int:
    """Farm tiles wanted: per dwarf of the population the fort is growing
    toward (as for bedrooms), more with a higher Agriculture."""
    pop = citizens
    if player_rules(s)["fort_goal"] != "maintain":
        target = growth_target(s, cfg)
        if target > citizens:
            pop = min(target, citizens + cfg["beds_ahead"])
    tiles = math.ceil(pop * cfg["farm_tiles_per_dwarf"] * factor(traits, "agriculture"))
    return max(cfg["min_farm_tiles"], min(cfg["max_farm_tiles"], tiles))


def thirsty_farm_extra(s: dict, memory, citizens: int, cfg: dict, want: int) -> tuple[int, bool]:
    """(0.105.23, 14.1 step 4b) Farm tiles beyond the target while drink is
    under its own target (not only under the urgent line): (tiles, whether
    the brewable seeds are mostly underground crops). B, the Monastery (2 Nov
    23:20): 74 tiles of plump helmets met `farm_target` (66 at 1 a dwarf),
    yet drink stayed at 3 a dwarf with 4 brewable plants in store: the
    harvest was eaten before the stills had it. x(1 + `farm_thirsty_share`),
    at most `farm_thirsty_max_tiles` more, and only with brewable seeds to sow
    in them and somewhere to lay plots (no farm failure on record)."""
    if "stocks" in _d(s.get("_errors")) or memory is None or getattr(memory, "farm_failure", ""):
        return 0, False
    if not drink_below_target(s, citizens, cfg, memory):
        return 0, False
    crops = [v for v in _d(_d(s.get("farms")).get("crops")).values() if isinstance(v, dict)]
    brew = [v for v in crops if v.get("brews") and int(v.get("seeds") or 0) > 0 and _l(v.get("seasons"))]
    seeds = sum(int(v.get("seeds") or 0) for v in brew)
    if seeds <= 0:
        return 0, False
    under = sum(int(v.get("seeds") or 0) for v in brew if v.get("underground"))
    extra = min(math.ceil(want * cfg["farm_thirsty_share"]), cfg["farm_thirsty_max_tiles"], seeds)
    return max(0, extra), under * 2 > seeds


def _farm_rule(s: dict, memory, traits: dict, citizens: int, cfg: dict, proposals: list, notes: list) -> None:
    """Farm plots, placed by the AI itself: on soil or muddy floor the fort
    already has, else a farm level dug in a soil layer."""
    if traits.get("agriculture", 0) <= -100 or citizens < cfg["min_dwarves_for_farms"]:
        return                                   # Hunt and gather: no farms
    have = idle_surface = int(_d(s.get("farms")).get("tiles") or 0)
    # (0.102.3) surface plots with nothing to sow (no seeds of a surface crop
    # that grows in a season; trees' seeds don't go in plots) don't count: the
    # Enxah fort had 42 tiles, 4 of its 6 plots on the surface and bare, and
    # ran dry on its 2 plump helmet plots
    fm = _d(s.get("farms"))
    plots, under = int(fm.get("plots") or 0), int(fm.get("plots_underground") or 0)
    crops = [v for v in _d(fm.get("crops")).values() if isinstance(v, dict)]
    if crops and plots and under < plots and not any(
            int(v.get("seeds") or 0) > 0 and _l(v.get("seasons")) and not v.get("underground") for v in crops):
        have = round(have * under / plots)
    # (0.105.5) Hammerstirred (2 Nov): the forts' surface plots could grow
    # nothing the fort had seeds of in any season (DF's menu: only "Leave
    # fallow"; its seeds nearly all underground crops) while two ran out of
    # drink: the report says so plot by plot, and such plots don't count
    live = farm_plots_live(s)
    if live:
        have = sum(int(p.get("tiles") or 0) for p in live if not p.get("dead"))
    under_seeds = sum(int(v.get("seeds") or 0) for v in crops
                      if v.get("underground") and _l(v.get("seasons")))
    under_tiles = sum(int(p.get("tiles") or 0) for p in live if p.get("underground") and not p.get("dead"))
    # (0.105.7 review) unknown drink isn't short
    thirsty = drink_known_short(s, cfg)
    # (0.105.7 review) underground plots the AI laid out lately count until
    # the report lists them (else asked again every cooldown)
    asked = _d(getattr(memory, "farm_under_asked", None))
    if (isinstance(asked.get("tick"), int)
            and 0 <= abs_tick(s) - asked["tick"] < cfg["farm_under_wait_days"] * TICKS_PER_DAY):
        # (0.105.33 B4) only the part the plot list doesn't show yet: the
        # bridge lists a placed plot at once, so it was counted twice
        pending = max(0, int(asked.get("tiles") or 0) - under_tiles)
        under_tiles = max(under_tiles, int(asked.get("tiles") or 0))
        have += pending
    # underground crops' seeds wait and no (or too few) underground plots for them
    under_need = (under_seeds >= cfg["seeds_per_plot"] and live
                  and under_tiles < min(under_seeds, cfg["under_farm_tiles"]) and (thirsty or under == 0))
    if under_need:
        have = min(have, under_tiles)
    idle_surface = max(0, idle_surface - have)       # (0.105.33 B4) never "+-20"
    pr = _d(s.get("projects"))
    open_ = [p for p in _l(pr.get("open")) if isinstance(p, dict)]
    levels = [p for p in open_ if p.get("kind") == "farms"]
    # plots of a farm level still being dug aren't buildings yet
    coming = sum(int(_d(p.get("summary")).get("farm_tiles") or 0) for p in levels if p.get("phase") == "dig")
    want = farm_target(s, traits, citizens, cfg)
    if under_need:
        want = max(want, min(under_seeds, cfg["under_farm_tiles"]))
    # (0.105.23, 14.1 step 4b) a thirsty fort farms more for its stills
    extra, extra_under = thirsty_farm_extra(s, memory, citizens, cfg, want)
    want = min(cfg["max_farm_tiles"], want + extra)
    if have + coming >= want * cfg["farm_refill_share"]:
        return
    if memory.farm_failure:
        # Only the player's problem when the fort is going hungry or thirsty;
        # while it's fed, a smaller field than the rule of thumb is fine.
        st = _d(s.get("stocks"))
        hungry = ("stocks" not in s["_errors"]
                  and (st.get("drink", 0) < citizens * cfg["urgent_drink_per_dwarf"]
                       or st.get("prepared_meals", 0) < citizens * cfg["urgent_meals_per_dwarf"]))
        text = f"farm plots: {memory.farm_failure}"
        if hungry:
            ask_player(notes, f"{text}. Food or drink is running low: make soil or muddy floor inside "
                       "the fort (dig into soil, or flood a floor to muddy it) and the AI will lay the "
                       "plots out")
        else:
            notes.append(f"{text} (the fort is fed, so this can wait)")
    # a farm level that couldn't be dug (no soil) isn't tried, or asked about, again for 4 weeks
    failed = memory.farm_failure_tick
    recent_fail = (failed is not None
                   and 0 <= abs_tick(s) - failed < cfg["farm_dig_retry_days"] * TICKS_PER_DAY)
    if recent_fail:
        return            # nowhere to farm a few days ago: asking every cooldown changes nothing
    # (a farm level gets one more slot than other levels: food comes first)
    dig = not levels and len(open_) < (pr.get("max_open") or 2) + 1
    n = max(4, min(400, want - have - coming))
    action = {"type": "farm_plots", "tiles": n, "dig": dig}
    first = not has_farms(s)
    if first:
        action["outside"] = True     # no farm at all: soil or grass under the sky will do until there's better
    if dig:
        action["style"] = layout_style(profile_from(traits, memory.culture or new_history()))
    if under_need or (extra and extra_under and not first):
        # (0.105.23) the thirsty fort's extra tiles go where its brewable seeds grow (plump helmets: underground)
        action["underground"] = True     # (0.105.5) subterranean floor only: plump helmets don't grow under the sky
        action.pop("outside", None)
    proposals.append(Proposal(
        "farms", action,
        f"{have} farm tiles" + (f" (+{idle_surface} on the surface with nothing to sow)" if idle_surface else "")
        + (f" (+{coming} being dug)" if coming else "")
        + f" for a fort heading to {want} tiles: lay out {n} more on soil or muddy floor"
        + (", or dig a farm level in soil" if dig else "")
        + (" (or on the surface: the fort has no farm)" if first and not under_need else "")
        + (f" (underground: {under_seeds} seeds of underground crops and {under_tiles} underground tiles"
           + (", drink is short" if thirsty else "") + ")" if under_need else "")
        + (f" (drink is under its target: {extra} tiles more for the brewable crops)" if extra else ""),
        2 if first or (under_need and thirsty) else 5))
