"""planner_growth: the fort's size and its own character (split out of
planner_building in 0.105.25, 13c): the population cap, newcomers and
sending dwarves away, the strain that holds them; further halls as the fort
grows (growth_candidates); the character slot and the weighted ladder of
levels. planner_building re-exports every name here."""

from __future__ import annotations

import math
from quirks import has_rule
from digest import _d, _l
from planner_core import *  # noqa: F401,F403

__all__ = ["BASIC_WORKSHOPS", "jail_plan", "tavern_factor", "LEARNING_NEEDS", "good_times", "strain_unhappy_lines", "fort_strain", "_pop_cap_rule", "_join_rule", "_shrink_rule", "CHARACTER_KINDS", "is_character_level", "character_slot_reserved", "character_slot_filter", "piety_slot", "LADDER_BASE", "LADDER_TRAITS", "_ladder_kind", "_ladder_word", "ladder_score", "GROWTH", "GROWTH_SOLDIERS", "GROWTH_ZONES", "GROWTH_MAX_OF", "GROWTH_AT", "GROWTH_EXTRA_SCORE", "GROWTH_MAX", "growth_want", "settled_times", "growth_wait", "growth_candidates", "TRAIT_NAMES_SHORT"]


# Workshops every fort needs; a workshops level is built when any is missing.
BASIC_WORKSHOPS = ["Still", "Kitchen", "Carpenters", "Masons", "Craftsdwarfs", "Butchers"]


def jail_plan(traits: dict, cfg: dict, citizens: int) -> dict | None:
    """Justice (lenient - harsh): None at -100 or lower (no jail: the sheriff
    beats or lets go); otherwise the jail comes at 15 / factor dwarves (30 at
    -100, 8 at +100) with a cell per 25 / factor dwarves (2 to 8: the bridge's
    limit; 0.96.0 said 12, which the bridge would have refused)."""
    j = traits.get("justice", 0) or 0
    if j <= -100:
        return None
    f = factor(traits, "justice")
    return {"min_dwarves": max(5, round(cfg["min_dwarves_for_jail"] / f)),
            "cells": max(2, min(8, int(citizens / (cfg["dwarves_per_cell"] / f))))}   # (the bridge takes 1-8)


def tavern_factor(traits: dict) -> float:
    """Outsiders: the tavern's size beside Welfare: x2^(Outsiders/200)
    (x1.41 at +100, x0.71 at -100): room for guests, or none."""
    return factor(traits, "welfare") * 2 ** ((traits.get("outsiders", 0) or 0) / 200)


LEARNING_NEEDS = ("LearnSomething", "ThinkAbstractly")


def good_times(s: dict, memory, traits: dict, cfg: dict) -> bool:
    """Prosperous and quiet enough for a set piece, in a fort that cares how
    it looks (Grandeur or Craftsmanship above 0): an established fort of
    `garden_min_citizens`+, well fed and watered, nothing threatening, hands
    to spare, and the last set piece `garden_every_years` ago (sooner for a
    grand fort, later for a plain one)."""
    if young_fort(s, cfg):
        return False
    # a fort that cares how it looks: Grandeur or Craftsmanship above the middle
    if traits.get("grandeur", 0) <= 0 and traits.get("craftsmanship", 0) <= 0:
        return False
    if (s["dwarves"].get("total") or 0) < cfg["garden_min_citizens"]:
        return False
    # (0.102.1) fed and watered, not rich: 15 drinks a dwarf (the young-fort
    # line) kept every big fort out (region2, 228 dwarves, ~2 a dwarf), so no
    # garden or great hall ever started at Grandeur 60
    if food_per_dwarf(s) < cfg["good_times_food_per_dwarf"]:
        return False
    drink = (_d(s.get("stocks")).get("drink") or 0) / max(1, s["dwarves"].get("total") or 1)
    if drink < cfg["good_times_drink_per_dwarf"]:
        return False
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return False
    idle_need = idle_line(s, cfg, "garden_idle_share") / (2 if traits.get("grandeur", 0) >= 50 else 1)
    if _idle_share(s) < idle_need:
        return False
    last = memory.last_garden_tick
    every = cfg["garden_every_years"] / factor(traits, "grandeur")
    return last is None or abs_tick(s) - last >= every * TICKS_PER_YEAR


def strain_unhappy_lines(s: dict, cfg: dict, traits: dict | None = None) -> tuple[float, float]:
    """(0.105.33) The unhappy shares that hold newcomers and let them come
    again, leaned by Growth: x factor(growth), kept within x0.5..x2 (the
    Merchant city at +60 holds at 30% and lets go at 18%, the Hermit hold at
    -60 at 13% and 8%; neutral forts 20% and 12%). Drink and meals stay
    unscaled: those are survival, not character."""
    t = traits if traits is not None else _traits(s)
    f = max(0.5, min(2.0, factor({"growth": float(_d(t).get("growth", 0) or 0)}, "growth")))
    return (round(cfg["strain_unhappy_pct"] * f, 1), round(cfg["strain_unhappy_ok_pct"] * f, 1))


def fort_strain(s: dict, cfg: dict, held: bool = False, traits: dict | None = None) -> list:
    """(0.104.106) Why the fort can't take more dwarves now: too many
    unhappy, drink or meals too short a dwarf. While held, the "ok" levels
    must all be reached to let go (no flicker). [] when it's fine or unread.
    (0.105.33) Never while the fort is young: on day 17 of every fort of the
    8 Nov run there were no meals yet ("meals 0 a dwarf"), and the cap sat at
    7 through year 250, turning away the first waves. The unhappy lines lean
    with Growth (strain_unhappy_lines).
    (0.105.33 fix) A young fort skips only the unhappy and meals lines: one
    short of drink still takes no newcomers."""
    young = young_fort(s, cfg)
    import outcomes
    m = outcomes.measure(s)
    out = []
    un, dr, me = m.get("unhappy_pct"), m.get("drink_pd"), m.get("meals_pd")
    k = "_ok" if held else ""
    # (0.105.8) and only once a few dwarves are unhappy: B (Monastery, 7
    # dwarves) was held at 7 from 12:24 for one miserable dwarf (14.3%, over
    # the 12% to let go), the only way under it nobody unhappy at all
    pop = int(_d(s.get("dwarves")).get("total") or 0)
    few = isinstance(un, (int, float)) and pop > 0 and un * pop / 100 < cfg.get("strain_unhappy_min", 3) - 0.01
    hold_at, ok_at = strain_unhappy_lines(s, cfg, traits)
    if isinstance(un, (int, float)) and un >= (ok_at if held else hold_at) and not few and not young:
        out.append(f"{un:g}% unhappy")
    if isinstance(dr, (int, float)) and dr < cfg["strain_drink" + k + "_pd"]:
        out.append(f"drink {dr:g} a dwarf")
    if isinstance(me, (int, float)) and me < cfg["strain_meals" + k + "_pd"] and not young:
        out.append(f"meals {me:g} a dwarf")
    return out


def _pop_cap_rule(s: dict, memory, cfg: dict, citizens: int, proposals: list, notes: list) -> None:
    """DF's population cap from the Growth slider (Expand) or the size the
    fort had when Maintain was chosen. Lasts for the session; set again
    after a restart."""
    rules_ = player_rules(s)
    so = s["society"]
    if not rules_["set_pop_cap"] or not isinstance(so.get("pop_cap"), int):
        return
    mode, n = growth_mode(s, cfg)
    if rules_["fort_goal"] == "maintain":
        cap = memory.maintain_pop or citizens
        strict = cap                       # births only to replace losses
        why = f"Maintain: hold the fort at {cap} dwarves"
    elif mode == "uncapped":
        cap = strict = cfg["uncapped"]
        why = "Growth: no population cap"
    elif mode == "shrink":
        cap = strict = cfg["min_citizens"]
        why = "Growth: no newcomers while the fort shrinks"
    else:
        cap = n
        strict = cap + 20
        why = f"Growth: the fort grows toward {cap} dwarves"
    strain = fort_strain(s, cfg, memory.strain_hold)
    holds = rules_["fort_goal"] != "maintain" and mode != "shrink"
    held_why = []
    if s.get("fps_low") and holds:
        # slow game: no newcomers for now. Held at the fort's size when it first
        # ran slowly (deaths don't shrink it further; births replace losses)
        cap = min(cap, memory.fps_cap or max(7, citizens))
        held_why.append(f"the game runs slowly (FPS {s.get('fps_low')})")
    if strain and holds:
        # (0.104.106) the fort can't carry the dwarves it has: no newcomers
        # until it can, held at its size when the strain began. (0.104.120)
        # its own size, and also while the game runs slowly: Teacheroar's
        # slow-game cap of 405 (29 Oct) held nothing at 296 dwarves, 51% unhappy
        # (0.104.138) and never above the fort's size now: the remembered size
        # (293 when the strain began) let 76 newcomers into a fort of 217 after
        # the massacre; births still come through the strict cap
        cap = min(cap, memory.strain_cap or max(7, citizens), max(7, citizens))
        held_why.append(f"the fort is strained ({'; '.join(strain)})")
    if held_why:
        strict = cap + 10
        why = " and ".join(held_why) + ": no newcomers for now"
    cap = max(7, cap)
    strict = max(strict, cap)
    # (item5) the floor: a fort under it takes migrants and has children
    # whatever the sliders say (the fort stays small and closed, not extinct);
    # Extreme-low Growth shrinks the fort on purpose and is left alone
    floor = int(cfg.get("survival_floor") or 0)
    babies = {}
    if floor and citizens < floor and mode != "shrink":
        if cap < floor or strict < floor + 10:
            why = (f"{why}; but the fort is down to {citizens} dwarves, under its floor of {floor}: "
                   f"migrants and births let in up to it")
        cap = max(cap, floor)
        strict = max(strict, floor + 10)
        for k, ck in (("baby_cap", "floor_baby_cap"), ("baby_pct", "floor_baby_pct")):
            have, want = so.get(k), int(cfg.get(ck) or 0)
            if isinstance(have, int) and not isinstance(have, bool) and want and have < want:
                babies[k] = want
        h = _d(s.get("homes"))
        if isinstance(h.get("couples"), int):
            notes.append(f"the fort is under its floor of {floor} dwarves ({citizens}; {h.get('couples')} married "
                         f"couple(s), {h.get('children') or 0} child(ren)): DF's cap stays open to migrants and "
                         "births whatever the sliders; under 20 dwarves DF sends no strange moods")
        if babies:
            why += ("; DF's baby cap raised (" + ", ".join(f"{k.replace('_', ' ')} {so.get(k)} -> {v}"
                                                          for k, v in babies.items()) + ")")
    # (0.105.46, I4) a fallen fort's cap opened to migrants past the strain and
    # slow-game holds (brain/planner_recovery.py open_cap)
    try:
        from planner_recovery import open_cap
        cap, strict, why = open_cap(s, memory, cfg, citizens, cap, strict, why, babies)
    except Exception as e:  # noqa: BLE001
        notes.append(f"the recovery's population cap failed ({type(e).__name__}): the cap as the sliders say")
    if (so["pop_cap"] != cap or (isinstance(so.get("strict_pop_cap"), int) and so["strict_pop_cap"] != strict)
            or babies):
        proposals.append(Proposal("pop_cap", {"type": "set_population_cap", "cap": cap, "strict": strict, **babies},
                                  f"{why}: population cap {so['pop_cap']} (strict {so.get('strict_pop_cap')}) "
                                  f"-> {cap} (strict {strict})", 4))


def _join_rule(s: dict, memory, cfg: dict, proposals: list) -> None:
    """(0.104.108, phase 12g; the player's findings after 38 years) Areas
    side by side on one level met only through the stairs, and corridors
    ended in rock. Every few days the bridge looks at the levels the AI built
    on, in turn, and joins two areas whose corridors come within 20 tiles
    through plain rock (2 wide, never into a room)."""
    if young_fort(s, cfg):
        return
    now = abs_tick(s)
    last = memory.last_join_tick
    wait = max(1, int(memory.join_wait_days or 2)) * TICKS_PER_DAY
    if last is not None and 0 <= now - last < wait:
        return
    proposals.append(Proposal("join_levels", {"type": "join_levels"},
                              "join areas on the same level that meet only through the stairs, "
                              "and corridors that end in rock; else widen a 1-wide corridor", 9))


def _shrink_rule(s: dict, memory, cfg: dict, citizens: int, proposals: list) -> None:
    """Extreme low Growth: send one dwarf away every so often (DFHack's
    emigration), never below the minimum. Not in Maintain."""
    mode, days = growth_mode(s, cfg)
    if mode != "shrink" or player_rules(s)["fort_goal"] == "maintain" or citizens <= cfg["min_citizens"]:
        return
    last = memory.last_expel_tick
    if last is not None and 0 <= abs_tick(s) - last < days * TICKS_PER_DAY:
        return
    proposals.append(Proposal("expel", {"type": "expel_dwarf"},
                              f"Growth (Extreme low): the fort shrinks, one dwarf leaves every {days} days; "
                              f"{citizens} now", 5))


# (0.105.10, 14.1 step 3) the levels that are the fort's own character: the
# weighted ladder's kinds, a set piece, or a level grown with the fort
CHARACTER_KINDS = {"jail", "suites", "tavern", "library", "barracks", "archery", "memorial", "temple", "garden"}


def is_character_level(a: dict) -> bool:
    """A start_project action (or an open project) that is the fort's own character."""
    a = _d(a)
    return bool(a.get("kind") in CHARACTER_KINDS or a.get("set_piece") or a.get("growth")
                or _d(a.get("summary")).get("set_piece"))


def character_slot_reserved(s: dict, traits: dict, cfg: dict, memory, open_: list) -> str | None:
    """(0.105.10, 14.1 step 3) Is the last free building slot the fort's own?
    Once the basics are met (beds for everyone, food and drink, the basic
    workshops, a dining hall), and no level of the fort's character is
    under way, one of the two slots goes to it: storage, bedrooms ahead of
    need and workshop levels for bottlenecks take the other. Why: the six
    forts' slots (y250-257) went to storage (9-13 levels each), bedrooms and
    workshop levels; barracks, temples, gardens and libraries got 0-4, so
    six presets built the same forts. A reason in words, or None."""
    if young_fort(s, cfg) or player_rules(s)["fort_goal"] == "maintain":
        return None
    # (review) a slow game or a crisis holds expansion: the need goes ahead
    if s.get("fps_low") or (memory is not None and _d(getattr(memory, "crisis", None)).get("why")):
        return None
    max_open = _d(s.get("projects")).get("max_open") or 2
    mine = set(getattr(memory, "character_projects", None) or []) if memory is not None else set()
    if len(open_) != max_open - 1 or any(is_character_level(p) or p.get("id") in mine for p in open_):
        return None
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 0))
    b = _d(s.get("buildings"))
    if int(_d(b.get("other")).get("Bed") or 0) < citizens:
        return None
    if not _d(b.get("zones")).get("DiningHall"):
        return None
    shops = {**_d(b.get("workshops")), **_d(b.get("furnaces"))}
    if any(not shops.get(w) for w in BASIC_WORKSHOPS):
        return None
    drink = int(_d(s.get("stocks")).get("drink") or 0) / citizens
    if food_per_dwarf(s) < cfg["character_food_per_dwarf"] or drink < cfg["character_drink_per_dwarf"]:
        return None
    return "beds, food, drink and workshops enough"


def character_slot_filter(s: dict, proposals: list, notes: list) -> list:
    """(0.105.10) While the last slot is the fort's own, no other rule's
    ordinary new level takes it (urgent levels have slots of their own)."""
    cs = _d(s.get("_character_slot"))
    if not cs:
        return proposals
    import crisis
    held = [p for p in proposals if p.action.get("type") == "start_project" and not p.action.get("urgent")
            and not is_character_level(p.action) and p.rule not in crisis.RECOVERY_RULES]
    if held:
        notes.append(f"the last building slot waits for the fort's own {cs.get('kind')} level: "
                     + ", ".join(sorted({f"{p.action.get('kind')} ({p.rule})" for p in held})) + " wait")
    return [p for p in proposals if p not in held]


def piety_slot(s: dict, traits: dict, cfg: dict, memory, open_: list) -> str | None:
    """(0.105.23, 14.1 step 4b) The Monastery's bend of the character slot:
    at Piety `character_piety_bend` and up, the last free slot may go to a
    shrine before food and drink reach the basics (B: its slot shut for
    want of drink while it held 3 drink a dwarf, the ladder's temple behind
    storage), with beds for all, a dining hall and the basic workshops, food
    and drink over their own lower lines, and never in a crisis or a slow
    game. A reason in words, or None (character_slot_reserved holds the slot
    itself once the basics are met)."""
    if (traits.get("piety", 0) or 0) < cfg["character_piety_bend"]:
        return None
    if young_fort(s, cfg) or player_rules(s)["fort_goal"] == "maintain":
        return None
    if s.get("fps_low") or (memory is not None and _d(getattr(memory, "crisis", None)).get("why")):
        return None
    if "stocks" in _d(s.get("_errors")):
        return None
    max_open = _d(s.get("projects")).get("max_open") or 2
    mine = set(getattr(memory, "character_projects", None) or []) if memory is not None else set()
    if len(open_) != max_open - 1 or any(is_character_level(p) or p.get("id") in mine for p in open_):
        return None
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 0))
    b = _d(s.get("buildings"))
    if int(_d(b.get("other")).get("Bed") or 0) < citizens or not _d(b.get("zones")).get("DiningHall"):
        return None
    shops = {**_d(b.get("workshops")), **_d(b.get("furnaces"))}
    if any(not shops.get(w) for w in BASIC_WORKSHOPS):
        return None
    drink = int(_d(s.get("stocks")).get("drink") or 0) / citizens
    if (food_per_dwarf(s) < cfg["character_piety_food_per_dwarf"]
            or drink < max(cfg["character_piety_drink_per_dwarf"], cfg["urgent_drink_per_dwarf"])):
        return None
    return (f"Piety {int(traits.get('piety', 0)):+d}: a shrine before food and drink are met "
            f"({food_per_dwarf(s):.0f} food, {drink:.1f} drink a dwarf)")


LADDER_BASE = {"jail": 9.5, "suites": 9.0, "tavern": 8.5, "library": 8.0, "barracks": 7.5, "archery": 7.0,
               "memorial": 6.5, "temple": 6.0, "garden": 5.5, "great hall": 5.0, "hospital": 5.5}


# (slider, divisor): +100 on the slider adds 100/divisor to the level's score
LADDER_TRAITS = {"jail": [("justice", 50)], "suites": [("deference", 50)],
                 "tavern": [("welfare", 100), ("outsiders", 100)], "library": [("welfare", 100), ("craftsmanship", 100)],
                 "barracks": [("militarism", 40)], "archery": [("militarism", 50)],
                 "memorial": [("grandeur", 100), ("piety", 100)], "temple": [("piety", 33)],
                 "garden": [("grandeur", 50)], "great hall": [("grandeur", 40)],
                 "hospital": [("welfare", 50)]}


def _ladder_kind(action: dict) -> str:
    return action.get("set_piece") or action.get("kind") or "?"


def _ladder_word(action: dict) -> str:
    return _ladder_kind(action)


def ladder_score(action: dict, s: dict, traits: dict, cfg: dict, memory=None) -> float:
    """(0.98) How urgent an optional level is: its place in the old ladder,
    plus the sliders that care about it, plus 2 when dwarves are distracted
    by the need it meets (a tavern for company, a library for learning, a
    temple for prayer), plus the fort's own leaning on those sliders (small:
    a tie-breaker that makes two default forts order things differently)."""
    kind = _ladder_kind(action)
    score = LADDER_BASE.get(kind, 5.0)
    lean = {}
    if memory is not None and isinstance(getattr(memory, "culture", None), dict):
        from leanings import totals
        lean = totals(memory.culture)
    for slider, div in LADDER_TRAITS.get(kind, []):
        score += ((traits.get(slider, 0) or 0) + 0.5 * (lean.get(slider, 0) or 0)) / div
    # (0.103.2) quirks that put a hall first
    if memory is not None:
        for rule, k in (("mead_hall", "tavern"), ("library_first", "library"), ("memorials_first", "memorial"),
                        ("legend_pride", "garden"), ("legend_pride", "great hall")):
            if kind == k and has_rule(getattr(memory, "culture", None), rule):
                score += 2.0
    if action.get("growth"):
        score += GROWTH_EXTRA_SCORE           # (0.104.85) a second hall after the first-time needs
    needs = {"tavern": SOCIAL_NEEDS, "library": LEARNING_NEEDS, "temple": ("PrayOrMeditate",)}.get(kind)
    if needs and unmet(s, *needs) >= cfg["needs_build_at"]:
        score += 2.0
    # (0.103.20) the season's character decision put this hall first
    if memory is not None:
        import season
        if season.raised(memory, abs_tick(s)) == kind:
            score += season.RAISE_BONUS
    return round(score, 2)


# kind: (where it is counted, dwarves for each one at neutral sliders, the
# sliders that want more, the words). The want: citizens / per x the mean of
# 2^(slider/100); soldiers for barracks.
GROWTH = {
    "tavern": ("INN_TAVERN", 70, ("outsiders", "welfare"), "tavern"),
    "library": ("LIBRARY", 120, ("craftsmanship", "welfare"), "library"),
    "hospital": ("HOSPITAL", 150, ("welfare",), "hospital"),
    "barracks": ("Barracks", 20, ("militarism",), "barracks"),
    # (0.104.161, 14.1) a martial fort's ranges grow with its army, a devout
    # fort raises grander temples, a harsh one a prison (counted by cells:
    # each jail cell is its own dungeon zone). The 14.1 exit test: War-hold
    # and Monastery, a game year each, built the same levels.
    "archery": ("ArcheryRange", 40, ("militarism",), "archery range"),
    "temple": ("TEMPLE", 100, ("piety",), "temple"),
    "jail": ("Dungeon", 25, ("justice",), "jail cell"),
}


GROWTH_SOLDIERS = {"barracks", "archery"}     # counted by soldiers, not citizens


GROWTH_ZONES = {"barracks", "archery", "jail"}  # counted by zones, not locations


GROWTH_MAX_OF = {"jail": 24}                  # cells: three jails of 8


# (0.104.161) kinds only a fort whose slider asks for them grows (slider, config key of its line)
GROWTH_AT = {"archery": ("militarism", "archery_more_militarism"), "temple": ("piety", "temple_more_piety"),
             "jail": ("justice", "prison_justice_at")}


GROWTH_EXTRA_SCORE = -3.5     # below a set piece at neutral sliders; a slider of +100 brings one level


GROWTH_MAX = 4                    # at most this many of each


def growth_want(kind: str, traits: dict, citizens: int, soldiers: int) -> int:
    where, per, sliders, _ = GROWTH[kind]
    f = sum(factor(traits, x) for x in sliders) / len(sliders)
    base = soldiers if kind in GROWTH_SOLDIERS else citizens
    return max(0, min(GROWTH_MAX_OF.get(kind, GROWTH_MAX), int(base * f // per)))


def settled_times(s: dict, memory, traits: dict, cfg: dict) -> bool:
    """(0.104.161, 14.1) Settled enough for the fort to keep growing its
    character (a second barracks, a prison, a grander temple): established,
    fed and watered, nothing that can reach the dwarves, not strained. Unlike
    good_times it doesn't ask that the fort cares how it looks, nor for idle
    hands or a set piece's wait: War-hold (Grandeur -40) never had good times,
    so its barracks never grew past the first."""
    if young_fort(s, cfg):
        return False
    cit = int(_d(s.get("dwarves")).get("total") or 0)
    if cit < cfg["garden_min_citizens"]:
        return False
    if food_per_dwarf(s) < cfg["good_times_food_per_dwarf"]:
        return False
    if (_d(s.get("stocks")).get("drink") or 0) / max(1, cit) < cfg["good_times_drink_per_dwarf"]:
        return False
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return False
    return not fort_strain(s, cfg)


def growth_wait(memory, kind: str, now: int, cfg: dict) -> str:
    """(0.104.161) Why a further hall of this kind waits ('' if it needn't):
    one a season, and a lifetime cap (a hall whose count never rises in the
    report must not be dug again and again)."""
    rec = _d(_d(getattr(memory, "culture", None)).get("growth_levels")).get(kind)
    if not isinstance(rec, dict):
        return ""
    if int(rec.get("n") or 0) >= cfg["growth_levels_max"]:
        return f"{rec.get('n')} built already"
    t = rec.get("tick")
    if isinstance(t, int) and 0 <= now - t < cfg["growth_gap_days"] * TICKS_PER_DAY:
        return f"the last one {(now - t) // TICKS_PER_DAY} days ago"
    return ""


def growth_candidates(s: dict, traits: dict, cfg: dict, memory, allow: dict, kinds_open, locations: dict,
                      zones: dict, citizens: int) -> list:
    """A second (or further) hall of a kind the fort has, while it has fewer
    than its size and sliders want, one kind at a time and at most one of a
    kind a season. (0.104.161) A kind the fort's sliders lean toward comes in
    settled times; any other waits for good times (which a plain fort never
    has: War-hold's barracks never grew past the first)."""
    settled = settled_times(s, memory, traits, cfg)
    good = good_times(s, memory, traits, cfg)
    if not (settled or good):
        return []
    soldiers = int(_d(s.get("military")).get("soldiers") or 0)
    now = abs_tick(s)
    out = []
    for kind, (where, per, sliders, word) in GROWTH.items():
        if not allow.get(kind, True) or kind in kinds_open:
            continue
        if not (good or (settled and sum(factor(traits, x) for x in sliders) / len(sliders) > 1)):
            continue                      # (0.104.161) the sliders don't ask for it: good times only
        if kind in GROWTH_AT and (traits.get(GROWTH_AT[kind][0], 0) or 0) < cfg[GROWTH_AT[kind][1]]:
            continue                      # (0.104.161) only a fort whose slider asks for it
        if kind == "jail" and (not justice_held(s) or not jail_plan(traits, cfg, citizens)):
            continue                      # nobody to fill the cells
        if kind == "archery" and not any(is_ranged(q) and (q.get("members") or 0) > 0
                                         for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict)):
            continue                      # no crossbows to train
        have = int((zones if kind in GROWTH_ZONES else locations).get(where) or 0)
        want = growth_want(kind, traits, citizens, soldiers)
        if have < 1 or have >= want:
            continue                      # the first one is the ladder's own; enough already
        if growth_wait(memory, kind, now, cfg):
            continue
        why = ", ".join(f"{TRAIT_NAMES_SHORT.get(x, x)} {int(traits.get(x, 0) or 0):+d}" for x in sliders
                        if traits.get(x))
        if kind == "tavern":
            action = {"type": "start_project", "kind": "tavern",
                      "tables": max(4, min(20, math.ceil(citizens / 10 * tavern_factor(traits))))}
        elif kind == "library":
            action = {"type": "start_project", "kind": "library", "bookcases": 6}
        elif kind == "hospital":
            action = {"type": "start_project", "kind": "hospital", "beds": max(4, min(12, citizens // 20))}
        elif kind == "archery":
            action = {"type": "start_project", "kind": "archery", "lanes": 3, "length": 12}
        elif kind == "temple":
            # a temple to all gods (no deity): the bridge knows "shrine" and "grand" only
            action = {"type": "start_project", "kind": "temple",
                      "size": "grand" if (traits.get("piety", 0) or 0) >= 100 else "shrine"}
        elif kind == "jail":
            action = {"type": "start_project", "kind": "jail", "cells": max(2, min(8, want - have))}
        else:
            action = {"type": "start_project", "kind": "barracks", "beds": 20}
        action["growth"] = True
        base = f"{soldiers} soldiers" if kind in GROWTH_SOLDIERS else f"{citizens} dwarves"
        tail = {"temple": f": another, {action.get('size')} temple to all gods",
                "jail": f": a prison, another jail of {action.get('cells')} cells"}.get(kind, f": another {word}")
        out.append((action, f"{base} and {have} {word}{'s' if have > 1 else ''}; the fort wants {want}"
                            + (f" ({why})" if why else "") + tail))
    return out


TRAIT_NAMES_SHORT = {"outsiders": "Outsiders", "welfare": "Welfare", "craftsmanship": "Craft",
                     "militarism": "Militarism", "piety": "Piety", "justice": "Justice"}
