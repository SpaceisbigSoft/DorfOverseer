"""(0.105.47) The herd by Husbandry: the slider's signature.

Why (the 14 Nov scorecard): the Garden fort (Husbandry +80) won no
Husbandry line: tame animals A 58 (War-hold), B 19, C 45, D 12, E 14,
F 30 (Garden); pastures A 9, B 5, C 8, D 2, E 3, F 7. Husbandry did three
things only (the tools rule in planner.py): nestboxes on at 0 or more,
DFHack's autobutcher on at 0 or less once the herd was big, and new
pastures sized up by its factor. Nothing kept a breeding pair, tamed a
caught animal, sheared or milked by what the animals had grown, and war
training (planner_military) ran in every fort alike. The War-hold's lead
came from that: DFHack's autobutcher spares war and hunting animals, its
gate dogs' pen was counted as a pasture (now not: ai-society
pasture_report), and nothing in the Garden fort bred more.

What the slider does now (reads the bridge's `herd` section, lua/ai-herd.lua):

  high (>= husbandry_high, 30)
    * breeders: per kind of grazer or egg layer with an adult pair, one
      male and herd_breed_females x the factor females (up to 8) kept from
      the butcher (the AI's kept list, lua/ai-herd.lua: autobutcher's mark
      taken off each report, slaughter_one skips them; no longer the
      nickname "Breeder", 0.105.51: named animals crashed DF 53.17);
    * caged wild animals tamed by the animal trainers (a dwarf given the
      labour first), while the herd is under its cap;
    * the AI's pastures kept ahead of the grazers' need (x the factor),
      not only made when an animal waits;
    * autobutcher's targets high (if it is on: the game ran slowly).
  middle
    * as before (autobutcher on for a big herd, at the middle targets).
  low (<= husbandry_low, -30)
    * autobutcher on once the herd passes herd_low_min, at the low
      targets (a female or two and a male of each kind); breeders let go.
  every level but low
    * wool shorn when an animal has wool grown now, a fortnight apart;
      milk drawn when an animal has milk now, every few days (no more
      "Shear animal: No creature" jobs, I7a).
  Militarism (planner_military._war_animal_rule, and here):
    * war training by Militarism (none below 0, war_animals_max x the
      factor above), hunting training from hunt_animals_militarism.

The caps: the herd's (the tools rule's herd_max: max(herd_min, citizens x
herd_per_dwarf) x the Husbandry factor) and the game's speed (fps_low):
no taming, no pasture ahead, while the herd is at its cap or the game runs
slowly; autobutcher still comes on everywhere when slow (the tools rule).
A Beast-friends fort (no_slaughter) never turns autobutcher on here.
Without the `herd` section (an older bridge, the fixtures) nothing here
proposes anything.
"""

from __future__ import annotations

import math

from digest import _d
from planner_core import Proposal, factor, player_rules, queued, young_fort, _has_shop
from quirks import has_rule

__all__ = ["herd_band", "herd_cap", "herd_targets_for", "breeders_wanted", "_husbandry_rules",
           "hunt_animals_wanted"]


def herd_band(traits: dict, cfg: dict) -> str:
    h = (traits or {}).get("husbandry", 0)
    if h >= cfg["husbandry_high"]:
        return "high"
    if h <= cfg["husbandry_low"]:
        return "low"
    return "mid"


def herd_cap(traits: dict, cfg: dict, citizens: int) -> float:
    """The tools rule's herd size: past it nestboxes stop, nothing tamed."""
    return max(cfg["herd_min"], citizens * cfg["herd_per_dwarf"]) * factor(traits or {}, "husbandry")


def herd_targets_for(traits: dict, cfg: dict) -> dict:
    t = cfg["herd_targets_" + herd_band(traits, cfg)]
    return dict(zip(("fk", "mk", "fa", "ma"), (int(x) for x in t)))


def breeders_wanted(traits: dict, cfg: dict) -> int:
    return max(1, min(8, round(cfg["herd_breed_females"] * factor(traits or {}, "husbandry"))))


def hunt_animals_wanted(traits: dict, cfg: dict) -> int:
    mil = (traits or {}).get("militarism", 0)
    if mil < cfg["hunt_animals_militarism"]:
        return 0
    return round(cfg["hunt_animals_max"] * factor(traits, "militarism"))


from util import int_or_zero as _int  # noqa: E402  (r6 c2) was a copy here


def _kinds_short_of_breeders(herd: dict, females: int) -> list:
    out = []
    for k in herd.get("kinds") or []:
        if not isinstance(k, dict) or not (k.get("grazer") or k.get("layer")):
            continue
        f, m = _int(k.get("f")), _int(k.get("m"))
        if f <= 0 or m <= 0:
            continue
        if _int(k.get("breeders_m")) < 1 or _int(k.get("breeders_f")) < min(females, f):
            out.append(str(k.get("name") or "?").lower())
    return out


def _husbandry_rules(s: dict, memory, traits: dict, cfg: dict, citizens: int,
                     proposals: list, notes: list) -> None:
    herd = _d(s.get("herd"))
    if not herd or herd.get("error") or not isinstance(herd.get("tame"), int):
        return
    traits = traits or {}
    band = herd_band(traits, cfg)
    tame = _int(herd.get("tame"))
    cap = herd_cap(traits, cfg, citizens)
    slow = bool(s.get("fps_low"))
    young = young_fort(s, cfg)
    tools = _d(s.get("tools"))
    culture = getattr(memory, "culture", None) if memory is not None else None
    no_slaughter = has_rule(culture, "no_slaughter")
    off_by_player = set(getattr(memory, "tools_player_disabled", None) or [])
    rules_ = player_rules(s)
    have = {p.rule for p in proposals}

    # --- breeders: kept at high Husbandry, let go at low -----------------
    if band == "high":
        females = breeders_wanted(traits, cfg)
        short = _kinds_short_of_breeders(herd, females)
        if short:
            proposals.append(Proposal(
                "herd_breeders", {"type": "herd_breeders", "females": females},
                f"Husbandry {traits.get('husbandry', 0)}: keep a breeding male and up to {females} females of "
                f"{', '.join(short[:5])}{'...' if len(short) > 5 else ''} from the butcher (the herd grows from them)", 5))
    elif band == "low" and _int(herd.get("breeders")) > 0:
        proposals.append(Proposal(
            "herd_breeders", {"type": "herd_breeders", "females": 0},
            f"Husbandry {traits.get('husbandry', 0)}: a small herd; the {herd['breeders']} kept breeders are "
            "let go (the butcher may take the surplus)", 6))

    # --- low: the surplus to the butcher ----------------------------------
    if (band == "low" and tame > cfg["herd_low_min"] and tools.get("autobutcher") is False
            and "autobutcher" not in off_by_player and not no_slaughter):
        proposals.append(Proposal(
            "herd_cull", {"type": "tool", "name": "autobutcher", "enabled": True},
            f"Husbandry {traits.get('husbandry', 0)}: {tame} tame animals and the fort keeps few: turn on "
            "autobutcher (the surplus to the butcher)", 5))

    # --- autobutcher's targets by the slider, while it is on --------------
    if tools.get("autobutcher") is True or any(p.rule == "herd_cull" for p in proposals):
        want = herd_targets_for(traits, cfg)
        got = _d(herd.get("targets"))
        if {k: got.get(k) for k in want} != want:
            proposals.append(Proposal(
                "herd_targets", {"type": "herd_targets", **want},
                f"autobutcher keeps {want['fa']} females and {want['ma']} male(s) of each kind, "
                f"{want['fk']}+{want['mk']} young (Husbandry {traits.get('husbandry', 0)})", 6))

    # --- taming the caged wild animals ------------------------------------
    tameable = _int(herd.get("tameable"))
    if band == "high" and tameable > 0 and not young:
        if slow or tame >= cap:
            notes.append(f"{tameable} caged wild animal(s) could be tamed, but "
                         + ("the game runs slowly" if slow else f"the herd is at its size ({tame} of {int(cap)})")
                         + ": left in their cages")
        elif _int(herd.get("trainers")) == 0:
            if "animal_trainer" not in have:
                proposals.append(Proposal(
                    "animal_trainer", {"type": "assign_labor", "job": "ANIMALTRAIN", "count": 1},
                    f"{tameable} caged wild animal(s) could be tamed and nobody may train animals: give one "
                    "dwarf the labour", 6))
        else:
            n = min(cfg["tame_wild_max"], tameable)
            kinds = ", ".join(str(_d(k).get("name") or "?").lower() for k in (herd.get("tameable_kinds") or [])[:3])
            proposals.append(Proposal(
                "tame_wild", {"type": "tame_wild", "max": n},
                f"Husbandry {traits.get('husbandry', 0)}: {tameable} caged wild animal(s) ({kinds}): the animal "
                f"trainers tame {n}", 6))

    # --- pastures ahead of the herd ----------------------------------------
    so = _d(s.get("society"))
    need = _int(herd.get("grazing_need"))
    if (band == "high" and need > 0 and rules_["pasture_animals"] and not slow and tame < cap
            and "new_pasture" not in have and not any(p.rule == "new_pasture" for p in proposals)
            and _int(so.get("ai_pastures")) < cfg["herd_pastures_max"]):
        grass = _int(so.get("ai_pasture_tiles"))
        want = math.ceil(need * cfg["herd_pasture_margin"] * factor(traits, "husbandry"))
        short = want - grass
        if short >= cfg["herd_pasture_min_deficit"]:
            tiles = max(9, min(600, short))
            proposals.append(Proposal(
                "new_pasture", {"type": "make_pasture", "tiles": tiles},
                f"Husbandry {traits.get('husbandry', 0)}: the grazers need {need} tiles of grass and the AI's "
                f"pastures have {grass}: a {tiles}-tile pasture ahead of the herd", 5))

    # --- wool and milk, from the animals that have them now ---------------
    farmers = _has_shop(s.get("buildings") or {}, "Farmers")
    if band != "low" and farmers and not young:
        wool = _int(herd.get("wool_now"))
        if wool > 0 and not queued(s, {"shear_creature"}):
            proposals.append(Proposal(
                "shearing", {"type": "work_order", "recipe": "shear_creature",
                             "amount": min(cfg["herd_produce_batch"], wool)},
                f"{wool} animal(s) have wool grown: shear them at the farmer's workshop", 6, True))
        milk = _int(herd.get("milk_now"))
        cheese = _int(_d(s.get("stocks")).get("cheese"))
        keep = citizens * cfg["cheese_per_dwarf"] * max(1.0, factor(traits, "husbandry"))
        if milk > 0 and cheese < keep and not queued(s, {"milk_creature"}):
            proposals.append(Proposal(
                "milking", {"type": "work_order", "recipe": "milk_creature",
                            "amount": min(cfg["herd_produce_batch"], milk)},
                f"{milk} animal(s) have milk now and {cheese} cheese is kept: milk them (for cheese)", 6, True))

    # --- hunting animals by Militarism ------------------------------------
    hunt_want = hunt_animals_wanted(traits, cfg)
    hunters = _int(herd.get("hunters"))
    cands = _int(herd.get("hunt_candidates"))
    if hunt_want > hunters and cands > 0 and not young and _int(herd.get("trainers")) > 0:
        n = min(2, hunt_want - hunters, cands)
        proposals.append(Proposal(
            "train_hunt", {"type": "train_hunt", "max": n},
            f"Militarism {traits.get('militarism', 0)}: {hunters} hunting animal(s) of {hunt_want} wanted: put "
            f"{n} to hunting training (they go out with the hunters)", 6))

    # what the herd is, said once a cycle while it is big or the slider is high
    if band == "high" or tame >= cap:
        notes.append(f"the herd: {tame} tame animals (the fort keeps about {int(cap)}), "
                     f"{_int(herd.get('breeding_pairs'))} kind(s) with a breeding pair, "
                     f"{_int(herd.get('breeders'))} breeders kept, {_int(herd.get('war'))} war and "
                     f"{hunters} hunting animals, {_int(herd.get('pets'))} pets")
