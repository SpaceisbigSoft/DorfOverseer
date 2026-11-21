"""(0.105.47, I7b) The unburied dead, the dead nobody can reach, and a cook
trained in a small fort.

Why (the 14 Nov forensics, I7b "why are B, D and E so unhappy?"): B asked
for a tomb level 23 times in 261-262 and every search failed ("no safe level
found near 1 staircase(s)"); it had 0 free tombs until summer 263 while 190+
dead lay unburied and 2-6 ghosts rose. Memorial slabs were made only once a
ghost walked (planner_society._dead_notes), though many bodies lay out of
reach (drowned, in ice, in the caverns), so their ghosts were bound to rise.
Automatic burial was found off on free tombs twice. D (8 dwarves) went ten
years without a good meal: its best cook had skill 1.

The rules here (lua/ai-welfare.lua does the work):

  burial_corner      coffins anywhere: (0.105.51) at once when the dead the
                     tombs can take outnumber the free tombs and no tomb
                     level is under way (burial_fallback_unburied, 1), or two
                     weeks after while one is (burial_fallback_days, 14; was
                     a season and 10 dead: C's ghost), or a week after a tomb
                     level's search failed (burial_fallback_refused_days):
                     coffins (each with a 1x1 tomb
                     that takes citizens) on free dug floor of the AI's
                     finished levels (a tomb level's spare tiles first, a
                     storage level, a workshop level). Not while the Rules
                     switch for tomb levels is off.
  burial_coffins     the coffins for them ordered (stone, wood while stone is
                     short) when fewer are free in store than wait
  slabs_ahead        a memorial slab ordered for each of the fort's dead whose
                     body can't be reached (or is gone), before a ghost rises
                     (the `dead` section's memorials_wanted; an EngraveSlab
                     order naming the dead, as DFHack's autoslab makes for a
                     ghost). Not while the Rules switch for slabs is off.
  slabs_ahead_blanks blank slabs for them (the mason engraves a blank one)
  slabs_ahead_place  the engraved slabs put up while no ghost walks (with a
                     ghost, _dead_notes' own `slabs` rule does it)
  burial_others      (0.105.51) the bodies DF never buries (dead.why.not_ours:
                     visitors', merchants', other civs') marked for a garbage
                     dump under the sky (mark_dump bodies), or one made
  train_cook         in a fort of cook_train_max_citizens or fewer whose best
                     free cook is under cook_train_below, while good meals are
                     wanted: the best free cook made the kitchens' only worker,
                     kept until gone (then the next best); released when the
                     fort grows past the limit.

Automatic burial in the AI's tombs: the bridge switches it on when a tomb
level is zoned and finished and when corner coffins are placed; the
existing `burial` rule (allow_burial) covers the corner tombs too.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (TICKS_PER_DAY, Proposal, _has_shop, abs_tick, player_rules, queued, stone_short,
                          AGENDA_THEMES, COOLDOWN_KEYS)
from planner_config import PLANNER_CONFIG

__all__ = ["_welfare_rules", "tombable_dead", "burial_fallback_due", "cook_train_due", "welfare_days", "welfare_slabs"]

AGENDA_THEMES["burial_corner"] = AGENDA_THEMES["burial_coffins"] = "bury the dead"
AGENDA_THEMES["burial_others"] = "the dead DF won't bury out to the dump"
AGENDA_THEMES["slabs_ahead"] = AGENDA_THEMES["slabs_ahead_blanks"] = AGENDA_THEMES["slabs_ahead_place"] = \
    "memorials for the dead nobody can reach"
AGENDA_THEMES["train_cook"] = "train a cook"
# (0.105.48 round 2, A9 #13) the rule is train_cook, its cooldown key
# cook_train_cooldown_ticks (select() read train_cook_cooldown_ticks: none,
# so the 2-day default instead of 7 days)
COOLDOWN_KEYS["train_cook"] = "cook_train_cooldown_ticks"

# the levels the bridge's tomb search refusals come under
TOMB_RULES = ("tombs_ghosts", "build", "tombs")


def _c(cfg: dict, k: str):
    return cfg[k] if k in cfg else PLANNER_CONFIG[k]


def _welfare(s: dict) -> float:
    try:
        from planner_core import _traits
        v = _traits(s).get("welfare", 0)
    except Exception:  # noqa: BLE001
        v = 0
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def welfare_days(s: dict, cfg: dict, key: str) -> int:
    """(r3, Welfare's say in burial) A burial wait in days by the Welfare
    slider: halved at Welfare +100, doubled at -100 (planner_core.factor),
    never under `r3_welfare_days_min` nor over twice the base. Welfare off
    (`r3_welfare_burial` False): the base."""
    base = int(_c(cfg, key))
    if not cfg.get("r3_welfare_burial", PLANNER_CONFIG.get("r3_welfare_burial", True)):
        return base
    d = round(base * 2 ** (-_welfare(s) / 100.0))
    return int(max(int(_c(cfg, "r3_welfare_days_min")), min(2 * base, d)))


def welfare_slabs(s: dict, cfg: dict) -> int:
    """(r3) Memorial slab orders a go: one more for each `r3_welfare_slab_step`
    of Welfare above 0."""
    base = int(_c(cfg, "slabs_ahead_max"))
    w = _welfare(s)
    if not cfg.get("r3_welfare_burial", PLANNER_CONFIG.get("r3_welfare_burial", True)) or w <= 0:
        return base
    return base + int(w // max(1, int(_c(cfg, "r3_welfare_slab_step"))))


def _book(memory) -> dict:
    b = getattr(memory, "welfare", None) if memory is not None else None
    if not isinstance(b, dict):
        b = {}
        if memory is not None:
            try:
                memory.welfare = b
            except Exception:  # noqa: BLE001
                pass
    return b


def tombable_dead(s: dict) -> int:
    """The unburied a tomb can take now, as planner_building.tombs_short counts them."""
    d = _d(s.get("dead"))
    unburied = int(d.get("unburied") or 0)
    why = _d(d.get("why"))
    if why and isinstance(why.get("free"), int):
        return int(why["free"]) + sum(int(why.get(k) or 0) for k in ("forbidden", "in_job", "carried"))
    if why:
        return max(0, unburied - sum(int(why.get(k) or 0) for k in ("outside", "unreachable", "not_ours", "dump")))
    return unburied


def _tomb_refused_at(memory) -> int | None:
    """When a tomb level was last refused (its search failed), or None."""
    last = None
    for key, r in _d(getattr(memory, "refusals", None)).items():
        rule, _, rest = str(key).partition(":")
        if rule in TOMB_RULES and '"tombs"' in rest and isinstance(r, dict) and isinstance(r.get("at"), int):
            last = r["at"] if last is None else max(last, r["at"])
    return last


def burial_fallback_due(s: dict, cfg: dict, memory=None) -> tuple[int, str]:
    """(short, why): how many more coffins the dead want now and in words why
    the tomb levels won't do; (0, "") when no fallback is due. Books in
    memory.welfare["short_since"] when the shortfall began."""
    d = _d(s.get("dead"))
    now = abs_tick(s)
    book = _book(memory)
    wel = _d(s.get("welfare"))
    waiting = int(_d(wel.get("corner")).get("waiting") or 0)
    short = tombable_dead(s) - int(d.get("free_tombs") or 0) - waiting
    if short <= 0:
        book.pop("short_since", None)
        return 0, ""
    since = book.get("short_since")
    if not isinstance(since, int) or since > now:
        since = book["short_since"] = now
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    tombs_open = any(p.get("kind") == "tombs" for p in open_)
    days = (now - since) // TICKS_PER_DAY
    refused = _tomb_refused_at(memory) if memory is not None else None
    fb_days = welfare_days(s, cfg, "burial_fallback_days")
    if days >= fb_days:
        return short, (f"the dead have outnumbered the free tombs for {days} days and the tomb level under way "
                       "isn't done" if tombs_open else
                       f"the dead have outnumbered the free tombs for {days} days and no tomb level came")
    if (refused is not None and 0 <= now - refused < fb_days * TICKS_PER_DAY
            and days >= welfare_days(s, cfg, "burial_fallback_refused_days") and not tombs_open):
        return short, "the tomb level's search failed (no safe level found)"
    if short >= _c(cfg, "burial_fallback_unburied") and not tombs_open:
        return short, (f"{short} more dead than free tombs and no tomb level under way (a body left unburied "
                       "may rise as a ghost)")
    return 0, ""


def _ordering(proposals: list, recipes: set) -> bool:
    """A work order for one of these recipes already proposed this cycle."""
    return any(_d(p.action).get("type") == "work_order" and _d(p.action).get("recipe") in recipes
               for p in proposals)


def _burial_rules(s: dict, cfg: dict, proposals: list, notes: list, memory, rules_: dict) -> None:
    if "dead" in s.get("_errors", {}):
        return
    d = _d(s.get("dead"))
    wel = _d(s.get("welfare"))
    corner = _d(wel.get("corner"))
    if player_rules(s)["levels"].get("tombs", True) and "welfare" not in s.get("_errors", {}):
        short, why = burial_fallback_due(s, cfg, memory)
        if short > 0:
            n = min(int(_c(cfg, "burial_corner_max")), short)
            proposals.append(Proposal("burial_corner", {"type": "coffins_anywhere", "max": n},
                                      f"{int(d.get('unburied') or 0)} dead unburied, {int(d.get('free_tombs') or 0)} free "
                                      f"tomb(s): {why}: {n} coffin(s) with a tomb each on free floor of the AI's "
                                      "finished levels (a tomb level's spare tiles, a storage corner)", 2))
        # their coffins: buildingplan waits for free ones in store
        waiting = int(corner.get("waiting") or 0)
        free = int(wel.get("coffin_items") or 0)
        b = _d(s.get("buildings"))
        recipes = {"stone_coffin", "wooden_coffin"}
        if waiting > free and not queued(s, recipes) and not _ordering(proposals, recipes):
            wood = int(_d(s.get("stocks")).get("wood") or 0)
            stone = not stone_short(s, waiting)
            recipe = "stone_coffin" if stone and _has_shop(b, "Masons") else (
                "wooden_coffin" if wood > 0 and _has_shop(b, "Carpenters") else None)
            if recipe:
                proposals.append(Proposal("burial_coffins", {"type": "work_order", "recipe": recipe,
                                                              "amount": waiting - free},
                                          f"{waiting} coffin(s) placed for the dead outside a tomb level wait and "
                                          f"{free} are free in store: make {waiting - free}", 3, True))
    # memorial slabs ahead for the dead nobody can reach
    wanted = int(d.get("memorials_wanted") or 0)
    if wanted > 0 and (rules_ or {}).get("engrave_slabs", True):
        b = _d(s.get("buildings"))
        su = _d(s.get("supplies"))
        if _has_shop(b, "Masons"):
            n = min(welfare_slabs(s, cfg), wanted)
            proposals.append(Proposal("slabs_ahead", {"type": "engrave_memorials", "max": n},
                                      f"{int(d.get('unreachable_dead') or 0)} of the fort's dead lie where nobody can "
                                      f"reach them (or their bodies are gone), {wanted} with no memorial slab: engrave "
                                      f"{n} now, before their ghosts rise", 3))
            blanks = su.get("slabs")
            pending = wanted + int(d.get("memorial_orders") or 0) + int(d.get("ghosts") or 0)
            if (isinstance(blanks, int) and blanks < min(pending, 10) and not queued(s, {"stone_slab"})
                    and not _ordering(proposals, {"stone_slab"}) and not stone_short(s, 1)):
                amt = min(10, pending) - blanks
                proposals.append(Proposal("slabs_ahead_blanks", {"type": "work_order", "recipe": "stone_slab",
                                                                  "amount": amt},
                                          f"memorial slabs wanted for {pending} dead and {blanks} blank slab(s) in "
                                          f"store: make {amt}", 4, True))
        else:
            notes.append(f"{wanted} of the fort's dead lie out of reach with no memorial slab: the AI engraves them "
                         "once the fort has a mason's workshop")
    ms = _d(s.get("supplies")).get("memorial_slabs")
    if isinstance(ms, int) and ms > 0 and not d.get("ghosts"):
        proposals.append(Proposal("slabs_ahead_place", {"type": "place_slabs", "max": min(20, ms)},
                                  f"{ms} engraved memorial slab(s) lie unbuilt: put them up, so the dead they name "
                                  "rest", 4))
    if d.get("unreachable_dead"):
        notes.append(f"{d['unreachable_dead']} of the fort's dead can't be reached ("
                     f"{int(d.get('unreachable_bodies') or 0)} out of the dwarves' walk, "
                     f"{int(d.get('gone_bodies') or 0)} with no body left), "
                     f"{int(d.get('unreachable_no_slab') or 0)} with no memorial slab")


COOK_UNFREE_DAYS = 3     # (0.105.51) the trainee not free to cook this many days running before the next takes over


def cook_unfree_long(s: dict, memory, cook: dict) -> bool:
    """(0.105.51) Has the trainee been not free to cook COOK_UNFREE_DAYS
    days running (each report seen free starts the count again)? R3 (15 Nov):
    D's trainee was swapped 97 times, two tavern keepers each week, each
    seen "not free" once (a stay in the recreation burrow). Without a memory:
    yes, as before."""
    if memory is None or not hasattr(memory, "cook_watch"):
        return True
    now = abs_tick(s)
    w = memory.cook_watch if isinstance(memory.cook_watch, dict) else {}
    if cook.get("free") is not False:
        if w:
            memory.cook_watch = {}
        return False
    since = w.get("since")
    if w.get("unit") != cook.get("unit") or not isinstance(since, int) or isinstance(since, bool) or since > now:
        memory.cook_watch = {"unit": cook.get("unit"), "since": now}
        return False
    return now - since >= COOK_UNFREE_DAYS * TICKS_PER_DAY


def cook_train_due(s: dict, cfg: dict, memory=None) -> str:
    """'train', 'release' or '' (nothing to do)."""
    sup = _d(s.get("supplies"))
    ck = _d(sup.get("cooks"))
    wel = _d(s.get("welfare"))
    cook = _d(wel.get("cook"))
    pop = int(_d(s.get("dwarves")).get("total") or 0)
    if cook.get("unit") is not None and pop > _c(cfg, "cook_train_max_citizens"):
        return "release"
    if pop <= 0 or pop > _c(cfg, "cook_train_max_citizens") or not _has_shop(_d(s.get("buildings")), "Kitchen"):
        return ""
    if cook.get("unit") is not None:
        # kept: asked again only when the trainee can't cook any more (the next best then)
        return "train" if cook.get("free") is False and cook_unfree_long(s, memory, cook) else ""
    best = max(int(ck.get("best") or 0), int(ck.get("best_any") or 0)) if ck else 0
    if best >= _c(cfg, "cook_train_below"):
        return ""
    egm = _d(_d(_d(s.get("needs")).get("needs")).get("EatGoodMeal"))
    wanting = max(int(egm.get("badly") or 0), int(egm.get("distracted") or 0))
    good = int(sup.get("good_meals") or 0)
    if wanting <= 0 or good / max(1, pop) >= _c(cfg, "good_meals_pd"):
        return ""
    return "train"


def _cook_rule(s: dict, cfg: dict, proposals: list, memory=None) -> None:
    if "welfare" in s.get("_errors", {}) or "supplies" in s.get("_errors", {}):
        return
    due = cook_train_due(s, cfg, memory)
    pop = int(_d(s.get("dwarves")).get("total") or 0)
    if due == "release":
        proposals.append(Proposal("train_cook", {"type": "train_cook", "release": True},
                                  f"the fort has grown to {pop}: the kitchens open to every cook again", 5))
    elif due == "train":
        ck = _d(_d(s.get("supplies")).get("cooks"))
        cook = _d(_d(s.get("welfare")).get("cook"))
        proposals.append(Proposal("train_cook", {"type": "train_cook"},
                                  (f"the trainee cook {cook.get('name') or ''} can't cook any more: the next best "
                                   "takes the kitchens" if cook.get("unit") is not None else
                                   f"a fort of {pop} with no good cook (the best free one is at skill "
                                   f"{int(ck.get('best') or 0)}) and good meals wanted: the best free cook kept at the "
                                   "kitchens so one dwarf learns"), 4))


def _others_dead_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.105.51) The bodies DF never buries (visitors', merchants', other
    civs' dwarves: the `dead` section's why.not_ours) marked for a garbage
    dump under the sky (mark_dump bodies, the bodies alone), or such a dump
    made first. E (R3): 10 such bodies lay indoors for years, kept as the
    fort's own; 668 indoor tiles of miasma, every citizen had seen a body."""
    if "dead" in s.get("_errors", {}) or "disposal" in s.get("_errors", {}):
        return
    d = _d(s.get("dead"))
    why = _d(d.get("why"))
    # the ones not yet marked nor in a dump (a bridge before 0.105.51: all of them)
    n = int(why["not_ours_loose"] if isinstance(why.get("not_ours_loose"), int) else why.get("not_ours") or 0)
    if n <= 0:
        return
    dis = _d(s.get("disposal"))
    if dis.get("siege"):
        return
    zones = [z for z in _l(dis.get("dump_zones")) if isinstance(z, dict)]
    if any(z.get("inside") is False for z in zones):
        most = min(int(_c(cfg, "burial_others_max")), 500)
        proposals.append(Proposal("burial_others", {"type": "mark_dump", "bodies": True, "junk": False,
                                                    "reasons": ["free", "other_dead"], "max": most},
                                  f"{n} dead of other civs (visitors, merchants: DF buries only its own) lie "
                                  "unburied: their bodies marked for the garbage dump outside, before they rot "
                                  "indoors", 4))
        return
    clearing = _d(_d(s.get("buildings")).get("clearing"))
    a = {"type": "place_surface", "kind": "dump"}
    if not clearing.get("dump") and not any(p.action == a for p in proposals):
        proposals.append(Proposal("burial_others", a,
                                  f"{n} dead of other civs lie unburied (DF buries only its own) and the fort has no "
                                  "garbage dump under the sky for them: make one outside", 5))


def _welfare_rules(s: dict, cfg: dict, proposals: list, notes: list, memory=None, rules_: dict | None = None) -> None:
    """(0.105.47) Called from plan() beside _dead_notes."""
    _burial_rules(s, cfg, proposals, notes, memory, rules_ or {})
    _others_dead_rule(s, cfg, proposals, notes)
    _cook_rule(s, cfg, proposals, memory)
