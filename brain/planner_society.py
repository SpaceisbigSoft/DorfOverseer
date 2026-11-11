"""planner_society: part of the planner (split out of planner.py in 0.104.83; see planner.py)."""

from __future__ import annotations
import json
import math
import re
from dataclasses import asdict, dataclass, field
from culture import layout_style, new_history, pick_stone, profile_from, stone_for
from learning import held_levels
import masterplan
import phases
from quirks import has_rule
from digest import _d, _l, normalize
from planner_core import *  # noqa: F401,F403
from planner_locations import *  # noqa: F401,F403  (13c: split out by theme)
from planner_health import *  # noqa: F401,F403  (13c: split out by theme)
from planner_visitors import *  # noqa: F401,F403  (13c: split out by theme)
from planner_moods import *  # noqa: F401,F403  (13c: split out by theme)

__all__ = ["_people_rules", "_comfort_rules", "stress_causes", "THOUGHT_WORDS", "_doctor_patient_rule", "_hospital_burrow_rule", "_calm_burrow_rule", "MOOD_WORKSHOPS", "PETITION_KINDS", "petition_orders_wanted", "_petition_rules", "_citizenship_notes", "_residency_rule", "residency_stance", "_location_access_rule", "note_heists", "heist_lockout", "heist_lockout_days", "visitor_shut", "location_stale", "note_locations", "mayor_meetings", "HEISTS_KEEP", "_jail_size_rule", "_convict_rule", "_break_fights_rule", "_sync_offices_rule", "patient_waits", "_health_rules", "TANTRUM_KEEP", "note_tantrums", "_noble_rooms_rule", "outsider_orders", "NEED_ADVICE", "JEWEL_RECIPES", "_recreation_rule", "_stress_care", "_needs_notes", "_location_supply_rules", "POST_LABORS", "STAFF_POSTS", "STAFF_MAX", "_traction_rule", "_wish_words", "_wish_met", "wish_key", "petition_lean", "_location_petition_rules", "_meeting_notes", "_grandeur_rule", "_location_value_rule", "_staff_rule", "_quick_location_rule", "_needs_rules", "_mood_rules", "mood_item_text", "_mood_materials", "_dead_notes", "AI_OFFICES", "_society_notes", "_booze_variety_rule", "drink_known_short_s", "_mood_make", "_mood_slaughter", "MOOD_CONSUMERS", "MOOD_TRADE_KEYS", "mood_trade_wants", "ghost_work_blocked"]


# (0.105.35) nothing waits for the player: the rules that took over what the
# Needs you asked (a mason for the ghosts' slabs, water for the bedridden)
for _k, _theme in (("ghost_masons", "a mason's for the ghosts' slabs"), ("ghost_mason", "a mason for the ghosts"),
                   ("care_feed", "water for the bedridden")):
    PLANNER_CONFIG.setdefault(f"{_k}_cooldown_ticks", 7 * TICKS_PER_DAY)
    AGENDA_THEMES.setdefault(_k, _theme)


def _convict_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(0.104.131, 12i) DF passes a sentence only once a case is convicted on
    its Justice screen, and nobody did: Teacheroar held 1,623 crimes, 399
    waiting for a trial (most tantrums' disorderly behaviour), the jail empty,
    and 61 citizens killed by citizens since y87. Solved cases (DF names the
    culprit) whose sentence has no hammer strikes are convicted a few a
    cycle, as the player's own conviction showed; DF passes the sentence.
    A lenient fort (Justice -50 or less) leaves them.
    (0.104.138) Only into free jail places, never while a beating waits (a
    convict with no place is beaten, and the guard kills: Teacheroar's sheriff
    killed 5 in the half hour after the convictions began, 10 in all); and the
    rule rests when its convictions bring no sentences (~100 convicted, 2 ever
    sentenced)."""
    j = _d(s.get("justice"))
    crimes = _d(j.get("crimes"))
    n = int(crimes.get("convictable") or 0)
    # (0.104.147) off: overnight 31 Oct-1 Nov the captain of the guard killed 7,
    # most of them patients, in the punishments that followed 31 convictions
    # (DF picks the sentence; a beating of a hurt dwarf kills). Back on only
    # when the jail can hold every sentence (cfg convict_on)
    if not cfg["convict_on"]:
        if n >= cfg["jail_convicts_wait"]:
            # (0.105.35) the AI's own decision, said as one (it was handed to the player)
            notes.append(f"{n} solved case(s) wait for a trial: the AI convicts no one (DF's beatings killed "
                         "patients), so they wait unjudged")
        return
    sentenced = int(crimes["sentenced_all"] if isinstance(crimes.get("sentenced_all"), int)
                    else _d(crimes.get("flags")).get("sentenced") or 0)
    now = abs_tick(s)
    w = _d(memory.convict_watch)
    memory.convict_watch = w
    if w.get("until") and now < int(w["until"]):
        notes.append(f"convictions rest: {w.get('given', 0)} case(s) convicted brought "
                     f"{max(0, sentenced - int(w.get('sentenced0') or 0))} sentence(s)")
        return
    if w.get("until"):
        w.clear()                                    # rested: try again from scratch
    if n <= 0:
        return
    traits = _traits(s)
    if int(traits.get("justice", 0) or 0) <= -50:
        return
    punish = _d(j.get("punish"))
    if int(punish.get("beatings") or 0) > 0:
        notes.append("no convictions while a beating waits (the guard beats a convict with no jail place, "
                     "and beatings kill)")
        return
    queued_ = int(punish.get("n") or 0)
    # (those serving time are in restraints_used already)
    waiting_ = max(0, queued_ - int(punish.get("prison") or 0))
    # (0.104.141) one place kept spare: a convict who finds none is beaten,
    # and the guard's beatings kill
    free = int(j.get("restraints") or 0) - int(j.get("restraints_used") or 0) - waiting_ - 1
    if free <= 0:
        if n >= cfg["jail_convicts_wait"]:
            notes.append(f"{n} solved case(s) wait for a trial and the jail has no spare place: no convictions "
                         "until it grows")
        return
    if int(w.get("given") or 0) >= cfg["convict_check_after"]:
        if sentenced - int(w.get("sentenced0") or 0) < cfg["convict_check_sentences"]:
            w["until"] = now + cfg["convict_rest_days"] * TICKS_PER_DAY
            notes.append(f"convictions rest {cfg['convict_rest_days']} days: {w['given']} convicted brought "
                         f"{max(0, sentenced - int(w.get('sentenced0') or 0))} sentence(s)")
            return
        w.clear()                                    # they work: count afresh
    w.setdefault("sentenced0", sentenced)
    k = min(n, cfg["convict_per_cycle"] + (2 if int(traits.get("justice", 0) or 0) >= 50 else 0), free)
    proposals.append(Proposal("convict", {"type": "convict", "max": k},
                              f"{n} solved case(s) wait for a trial nobody gives (DF sentences only convicted ones): "
                              f"convict {k}, the oldest first ({free} free jail place(s), {queued_} punishment(s) waiting)", 4))


def _break_fights_rule(s: dict, memory, cfg: dict, proposals: list) -> None:
    """(0.104.139, phase 11) The fort's own killing each other: DF's
    conflicts draw friends and kin in and turn lethal (Teacheroar, 27-31 Oct:
    460 citizens killed by citizens, 25 -> 144 a day, 356 strangled, a third
    in the hospital; no crime recorded, so justice can't reach it). While a
    citizen killed by a citizen is this recent, or tantrums come thick,
    DFHack's fix/loyaltycascade breaks the fights up (a tenth of a day at most)."""
    now = abs_tick(s)
    recent = [t for t in _l(getattr(memory, "fight_deaths", None))
              if isinstance(t, int) and 0 <= now - t < cfg["break_fights_days"] * TICKS_PER_DAY]
    # (review) only on deaths (not tantrums alone), and never while enemies are
    # about: the script takes every citizen out of every conflict, soldiers' too
    if not recent:
        return
    o = _d(s.get("others_on_map"))
    if o.get("threats_that_can_reach_dwarves") or any(isinstance(t, dict) and t.get("invader")
                                                       for t in _l(o.get("threats"))):
        return
    why = f"{len(recent)} citizen(s) killed by citizens in {cfg['break_fights_days']} days"
    proposals.append(Proposal("break_fights", {"type": "break_fights"},
                              f"{why}: break up the fights among the fort's own (DFHack fix/loyaltycascade)", 0))


def _jail_size_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(0.104.52) A jail too small for the fort's crimes: with tantrums coming
    thick and every restraint in use (or fewer than a tenth of the citizens
    could be held), a chain put in a jail zone, its rope or chain ordered.
    Enxah: 2 chains for 73 dwarves, a tantrum a minute, beatings, one fatal."""
    j = _d(s.get("justice"))
    jails = [z for z in _l(j.get("jails")) if isinstance(z, dict) and isinstance(z.get("id"), int)]
    if not jails or not justice_held(s):
        return
    cit = int(_d(s.get("dwarves")).get("total") or 0)
    have, used = int(j.get("restraints") or 0), int(j.get("restraints_used") or 0)
    want = max(2, min(cfg["jail_restraints_max"], math.ceil(cit / cfg["dwarves_per_restraint"])))
    # (0.104.141, 12k) the jail by the convicts waiting: solved cases the
    # conviction rule holds back for want of a spare place grow it too
    pressing = (int(_d(j.get("crimes")).get("convictable") or 0) >= cfg["jail_convicts_wait"]
                and have < 2 * want)              # (review) never past twice what the fort wants
    spare = 2 if pressing else 1
    if have >= want and used < have - (2 if pressing else 0):
        return
    # (0.104.138) with places free there's no hurry: only when nearly full, or
    # under half of what the fort wants (Teacheroar: 10 chains, 2 in use)
    if used < have - spare and have >= want // 2:
        return
    if (tantrums_recent(s, memory) < cfg["urgent_jail_tantrums"] and int(_d(j.get("punish")).get("beatings") or 0) == 0
            and not pressing):
        return
    # (0.104.138) only a jail with free floor (the bridge's own check)
    roomy = [z for z in jails if not isinstance(z.get("free"), int) or z["free"] > 0]
    if not roomy:
        open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
        if not any(p.get("kind") == "jail" for p in open_) and player_rules(s)["levels"].get("jail", True):
            proposals.append(Proposal("jail_more", {"type": "start_project", "kind": "jail", "cells": 8},
                                      f"the jails are full to the walls ({have} restraints, {used} in use, no free "
                                      f"floor) for {cit} dwarves: dig another jail with 8 cells", 3))
        else:
            notes.append(f"the jails have no free floor for another chain ({have} restraints for {cit} dwarves)")
        return
    zone = min(roomy, key=lambda z: int(z.get("chains") or 0) + int(z.get("cages") or 0))
    proposals.append(Proposal("jail_size", {"type": "place_in_zone", "zone_id": zone["id"], "what": "chain"},
                              f"the jail holds {have} ({used} in use) for {cit} dwarves and the crimes come thick: "
                              "another chain (or the guard beats the offenders)", 3))
    _restraint_order(s, 1, cfg, proposals, notes)


def _sync_offices_rule(s: dict, proposals: list) -> None:
    """(0.101.6) Appointed nobles the game can't see (its duty lists miss
    them): the manager never handed out an order, the broker never traded."""
    o = _d(s.get("offices"))
    n = int(o.get("unlisted") or 0) + int(o.get("stale_listed") or 0)
    if n > 0:
        proposals.append(Proposal("sync_offices", {"type": "sync_offices"},
                                  f"{o.get('unlisted') or 0} appointed post(s) are missing from the game's duty lists "
                                  "(it can't see that manager, broker or doctor): put them on", 1))


OFFICE_FIRST = ("MANAGER", "MAYOR", "EXPEDITION_LEADER")     # (0.104.168) an office whatever Deference says


def _noble_rooms_rule(s: dict, cfg: dict, proposals: list, memory=None) -> None:
    """A noble whose office asks for a bedroom, office, dining room or tomb
    of their own gets a free one (an unhappy noble makes demands); which of
    them by Deference (0.96, noble_room_kinds)."""
    nr = _d(s.get("noble_rooms"))
    free = dict(_d(nr.get("free")))
    kinds_given = noble_room_kinds(_traits(s) if isinstance(s.get("settings"), dict) else {}, memory)
    # (0.100.2) the manager's office first, whatever Deference says: it's
    # where work orders are taken up, not a noble's comfort
    # (0.104.168) and the mayor's (the expedition leader's before one is
    # elected): the citizens' complaints are heard there (DF's MEET_WORKERS)
    nobles = sorted((n for n in _l(nr.get("nobles")) if isinstance(n, dict)),
                    key=lambda n: (OFFICE_FIRST.index(n.get("office")) if n.get("office") in OFFICE_FIRST
                                   else len(OFFICE_FIRST)))
    for n in nobles:
        for kind in _l(n.get("needs")):
            given = kind in kinds_given or (kind == "office" and n.get("office") in OFFICE_FIRST)
            if given and (free.get(kind) or 0) > 0:
                free[kind] -= 1
                proposals.append(Proposal("noble_rooms", {"type": "give_room", "unit_id": n.get("unit_id"),
                                                          "kind": kind, "name": n.get("name")},
                                          f"{n.get('name')} has no {kind} of their own"
                                          f"{' (dining room)' if kind == 'dining' else ''}: give them a free one", 4))


# what helps a need the AI doesn't build for, in words
NEED_ADVICE = {
    "DrinkAlcohol": "more drink (the still)", "EatGoodMeal": "better meals (the kitchen)",
    "CraftObject": "crafting work", "AdmireArt": "engravings and statues", "MartialTraining": "squad training",
    "PracticeSkill": "work at their trade", "StayOccupied": "work to do", "BeCreative": "music, poetry, crafts",
    "Excitement": "something happening", "SeeAnimal": "animals about", "Wander": "places to walk",
    "BeWithFamily": "time with family", "HelpSomebody": "someone to help", "AcquireObject": "things to own",
    "BeExtravagant": "fine things", "TakeItEasy": "rest", "PrayOrMeditate": "a temple",
    "Socialize": "a tavern", "BeWithFriends": "a tavern", "MakeMerry": "a tavern", "LearnSomething": "a library",
    "ThinkAbstractly": "a library", "HearEloquence": "performers (a tavern)",
}


JEWEL_RECIPES = ("stone_amulet", "stone_bracelet", "stone_ring", "stone_earring")


def _recreation_rule(s: dict, cfg: dict, worst: list, proposals: list | None, memory=None) -> None:
    """(0.104.78) The recreation burrow (players' cure for dwarves too busy to
    meet their needs): the very unhappy and miserable civilians moved into a
    burrow over the taverns, temples, library, dining halls, bedrooms and food
    piles, so they take no work there; each back to work once no longer
    unhappy, or after `recreation_days`. The bridge picks who; the planner asks
    while anyone civilian is that low, or while the burrow has members (to let
    them out). Not while threats can reach the fort (the alert's burrow rules
    then), nor in a fort under `recreation_min_citizens`.

    (0.105.33, L6/B4) Members are never left behind: when the rule stops (a
    threat, the fort shrunk, the report's recreation section unreadable) and
    the burrow has members, the burrow is emptied ({"release": true}, with
    max 1 so a bridge that doesn't know `release` only lets the recovered
    out and moves nobody in). The bridge also checks the members at every
    report (thirst, hunger, a tantrum, a patient, too long) and lets them
    all out when no tick came for a long while. (The `recreation` Rules
    switch it read never existed: dropped.)"""
    if proposals is None:
        return
    rec = _d(s.get("society")).get("recreation")
    members = int(_d(rec).get("members") or 0)
    citizens = int(_d(s.get("dwarves")).get("total") or 0)
    why = None
    if isinstance(rec, dict) and rec.get("error"):
        why = "the recreation burrow's status is unreadable"
    elif citizens < cfg["recreation_min_citizens"]:
        why = f"the fort is under {cfg['recreation_min_citizens']} citizens"
    elif _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        why = "threats can reach the dwarves"
    if why:
        if members > 0 or (isinstance(rec, dict) and rec.get("error")):
            proposals.append(Proposal("recreation", {"type": "recreation", "release": True, "max": 1,
                                                     "days": cfg["recreation_days"]},
                                      f"{why}: everyone in the recreation burrow back to the fort", 4))
        return
    low = [x for x in worst if x.get("stress") in ("miserable", "very_unhappy") and not x.get("squad")]
    # (0.104.80) civilians badly wanting friends get a few short stays too
    bwf = _d(_d(_d(s.get("needs")).get("needs")).get("BeWithFriends"))
    lonely = int(bwf.get("badly") or 0) - int(bwf.get("badly_soldiers") or 0)
    # (0.104.137) scaled to the fort: 4 places for friends and 8 in all were
    # set for forts of 50 (Teacheroar: 221 dwarves, 85 badly wanting friends)
    friends = (min(10, max(cfg["recreation_friends"], lonely // 5))
               if lonely > 0 and int(bwf.get("badly") or 0) >= cfg["recreation_friends_share"] * citizens else 0)
    # (0.104.139) while the fort's own are killing each other, no crowd of the
    # unhappiest packed together (Teacheroar: 20 in the burrow, the fights
    # spread through the halls): the base few, and no extra for friends
    now_ = abs_tick(s)
    fighting = any(isinstance(t, int) and 0 <= now_ - t < cfg["break_fights_days"] * TICKS_PER_DAY
                   for t in _l(getattr(memory, "fight_deaths", None)))
    if fighting:
        friends = 0
    if low or members or friends:
        cap = cfg["recreation_max"] if fighting else min(30, max(cfg["recreation_max"], citizens // 20))
        action = {"type": "recreation", "max": cap,
                  "days": cfg["recreation_days"]}
        if friends:
            action.update(friends=friends, friend_days=cfg["recreation_friend_days"])
        proposals.append(Proposal("recreation", action,
                                  f"{len(low)} civilian(s) very unhappy or worse"
                                  + (f", {lonely} civilian(s) badly wanting friends" if friends else "")
                                  + (f", {members} in the recreation burrow" if members else "")
                                  + ": the unhappiest off work in the taverns, temples and halls"
                                  + (", the lonely a week among the others" if friends else "")
                                  + ", the recovered back to work",
                                  4))


def _stress_care(s: dict, cfg: dict, worst: list, proposals: list | None, memory=None) -> None:
    """(0.102.4) A dwarf breaking down gets what the AI can give (DF wiki,
    Keeping your dwarves unstressed): out of the squad (not its leader, not
    while threats can reach the fort; stronger Welfare acts on the very
    unhappy too), and a bedroom of their own if one is free. Monastery's
    performer stumbled about 4 times in two months, went mad and died."""
    if proposals is None:
        return
    welfare = _traits(s).get("welfare", 0) or 0
    labels = ("miserable", "very_unhappy") if welfare >= 50 else ("miserable",)
    crisis = [x for x in worst if x.get("stress") in labels and x.get("id") is not None]
    if not crisis:
        return
    quiet = not _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves")
    now = abs_tick(s)
    for x in crisis:
        # (0.103.9) not one who longs to fight or train: the squad is what meets that
        p = Proposal("stress_care", {"type": "squad_release", "unit_id": x["id"]},
                     f"{x.get('name')} is {str(x.get('stress')).replace('_', ' ')}: out of the "
                     "squad (soldiering weighs on the stress-prone)", 3)
        # (0.103.12) nor one the game kept in (the bridge refuses a dwarf who
        # longs to train): Ber's release was asked for every cycle and the
        # free bedroom below never came
        if memory is not None and _refused_wait(memory, p, now) is not None:
            continue
        if (x.get("squad") and not x.get("leader") and quiet and player_rules(s)["fill_squads"]
                and not x.get("wants_fight")             # (0.104.38) the bridge says so (any of their needs)
                and not set(_l(x.get("unmet"))) & {"MartialTraining", "Fight"}):
            proposals.append(p)
            return
    free = int(_d(_d(s.get("noble_rooms")).get("free")).get("bedroom") or 0)
    for x in crisis:
        if x.get("bedroom") is False and free > 0:
            proposals.append(Proposal("stress_care", {"type": "give_room", "unit_id": x["id"], "kind": "bedroom"},
                                      f"{x.get('name')} is {str(x.get('stress')).replace('_', ' ')} and has no "
                                      "room of their own: give them a free bedroom", 3))
            return


def _needs_notes(s: dict, cfg: dict, notes: list, proposals: list | None = None, memory=None) -> None:
    """What the dwarves miss most, and the most stressed of them."""
    if memory is not None and proposals is not None:
        _shelter_supply_rule(s, memory, proposals, notes)       # (0.105.36, D5)
    nd = s.get("needs")
    if not isinstance(nd, dict) or "error" in nd:
        # (0.105.33, B4) the recreation burrow's members still let out
        _recreation_rule(s, cfg, [], proposals, memory)
        return
    rows = sorted(((int(_d(v).get("distracted") or 0), k) for k, v in _d(nd.get("needs")).items()), reverse=True)
    top = [(n, k) for n, k in rows if n >= cfg["needs_note_at"]][:4]
    if top:
        notes.append("dwarves distracted by unmet needs: " + "; ".join(
            f"{k} {n}" + (f" ({NEED_ADVICE[k]})" if k in NEED_ADVICE else "") for n, k in top))
    gods = sorted(((n, g) for g, n in _d(nd.get("deities")).items()), reverse=True)[:3]
    if gods and unmet(s, "PrayOrMeditate") >= cfg["needs_note_at"]:
        notes.append("dwarves wanting to pray, by god: " + ", ".join(f"{g} {n}" for n, g in gods))
    pet = _d(nd.get("petitions"))
    want = [f"a temple to {g}" for g in _l(pet.get("temples"))] + [f"a {p} guildhall" for p in _l(pet.get("guildhalls"))]
    # (0.89) the AI builds them itself unless the Rules switch is off
    if want and not player_rules(s).get("answer_locations", True):
        # (0.105.35) the player's own switch: said, not handed back to them
        notes.append(f"the fort agreed to petitions it hasn't kept: {', '.join(want[:4])}; the AI doesn't build "
                     "them while the Rules switch for building them is off")
    worst = [x for x in _l(nd.get("stressed")) if isinstance(x, dict)]
    miserable = [x for x in worst if x.get("stress") == "miserable"]
    _stress_care(s, cfg, worst, proposals, memory)
    _soldier_swap(s, cfg, proposals, memory)
    _recreation_rule(s, cfg, worst, proposals, memory)
    # (0.104.133) the full counts (the list keeps the worst 8: "8 miserable" was
    # said with 94 miserable and 48 very unhappy)
    stress = _d(_d(s.get("dwarves")).get("stress"))
    n_mis = max(len(miserable), stress["miserable"] if isinstance(stress.get("miserable"), int) else 0)
    n_worst = max(len(worst), n_mis + (stress["very_unhappy"] if isinstance(stress.get("very_unhappy"), int) else 0))
    if miserable:
        # (0.105.35) a note of what the AI does (stress care, time off, the
        # calm burrow for a tantrum), not a Needs you
        notes.append(f"{n_mis} dwarf(s) are miserable and may throw tantrums (the worst: "
                     + "; ".join(f"{x.get('name')} (missing {', '.join(x.get('unmet') or []) or '?'})"
                                 for x in miserable[:3])
                     + "): the AI gives them what they miss where it can, time off in the recreation burrow, "
                       "and keeps a tantrum away from the others")
    elif worst:
        notes.append(f"{n_worst} dwarf(s) very unhappy: "
                     + "; ".join(f"{x.get('name')} (missing {', '.join(x.get('unmet') or []) or '?'})"
                                 for x in worst[:3]))


def stress_causes(s: dict) -> list:
    """(0.104.157) The census of what stresses the fort (DF's thoughts of the
    last 28 days, the worst first): [{thought, citizens, stress, emotion}]."""
    return [c for c in _l(_d(_d(s.get("needs")).get("stress_causes")).get("causes")) if isinstance(c, dict)]


def _cause_citizens(s: dict, thought: str) -> int:
    for c in stress_causes(s):
        if c.get("thought") == thought:
            return int(c.get("citizens") or 0)
    return 0


THOUGHT_WORDS = {"NoShoes": "no shoes", "DrinkWithoutCup": "drinking without a cup", "Attacked": "being attacked",
                 "MajorInjuries": "bad injuries", "Argument": "arguments", "AnnoyedVermin": "vermin",
                 "Decay": "rotting bodies", "SleptRoughFloor": "sleeping on the floor", "Uncovered": "no clothes on",
                 "Rest": "being kept resting", "NeedsUnfulfilled": "unmet needs"}
THOUGHT_WORDS.update({"UnableComplain": "complaints nobody heard"})   # (0.104.168)
THOUGHT_WORDS.update({"SameBooze": "drinking the same booze"})      # (0.105.24)


def _booze_variety_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(0.105.24) Drink of one kind. 2-5 Nov the stress census named
    SameBooze ("the same old booze") the worst cause in B and E (citizens
    upset by it summed over the night's notes: E 74,107, B 61,527, C 11,126;
    the next, arguments, 23,286 in E) and the AI had no rule for it: the forts
    brewed one crop. Drinks of more kinds: fruit brewed (another drink than
    the plants'), and the AI's own farm plots set to grow a second brewable
    crop the fort has seeds of (set_farm_crops variety)."""
    n = _cause_citizens(s, "SameBooze")
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    if n < max(cfg["booze_variety_min"], citizens * cfg["booze_variety_share"]):
        return
    su, b = _d(s.get("supplies")), _d(s.get("buildings"))
    kinds = su.get("drink_kinds")
    if isinstance(kinds, int) and kinds >= cfg["booze_kinds_enough"]:
        notes.append(f"{n} citizens upset by drinking the same booze, with {kinds} kinds of drink in store")
        return
    did = []
    growths = int(su.get("brewable_growths") or 0)
    room = int(su.get("empty_barrels") or 0) + int(su.get("empty_pots") or 0)
    # (0.105.26) the barrels the AI's open brew jobs and this cycle's brews
    # will fill are no room; and a fruit brew the drink rule asks for this
    # cycle is the variety (both passed select: 12 + 5 brews for 12 barrels)
    from planner_farms import brew_jobs_open
    brewing = [p for p in proposals if isinstance(p.action, dict) and p.action.get("type") == "work_order"
               and p.action.get("recipe") in BREW_RECIPES]
    room -= brew_jobs_open(s) + sum(int(p.action.get("amount") or 0) for p in brewing)
    fruit_now = any(p.action.get("recipe") == "brew_drink_from_fruit" for p in brewing)
    if (growths >= cfg["booze_fruit_min"] and _has_shop(b, "Still") and room > 0 and not fruit_now
            and not queued(s, {"brew_drink_from_fruit"})):
        amount = max(1, min(cfg["booze_fruit_batch"], growths // 5, room))
        proposals.append(Proposal("booze_variety", {"type": "work_order", "recipe": "brew_drink_from_fruit",
                                                    "amount": amount},
                                  f"{n} citizens are upset at drinking the same booze"
                                  + (f" ({kinds} kind(s) in store)" if isinstance(kinds, int) else "")
                                  + f": brew {amount} from the {growths} fermentable fruit and leaves "
                                    "(a drink of another kind)", 4, True))
        did.append("fruit")
    from planner_industry import crops_owned
    fm = _d(s.get("farms"))
    crops = {k: v for k, v in _d(fm.get("crops")).items() if isinstance(v, dict)}
    season = str(fm.get("season") or "")
    under, surface = int(fm.get("plots_underground") or 0), int(fm.get("plots_surface") or 0)

    def grows(c):
        return (season in _l(c.get("seasons")) and int(c.get("seeds") or 0) > 0
                and ((under > 0) if c.get("underground") else (surface > 0)))

    brew = [k for k, c in crops.items() if c.get("brews")]
    planted = [k for k in brew if int(crops[k].get("planted") or 0) > 0]
    spare = [k for k in brew if k not in planted and grows(crops[k])]
    if crops_owned(s, memory) and len(planted) <= 1 and spare:
        proposals.append(Proposal("booze_variety", {"type": "set_farm_crops", "variety": True,
                                                    "drink": drink_known_short_s(s, cfg)},
                                  f"{n} citizens are upset at drinking the same booze and the farms grow "
                                  f"{'only ' + planted[0].lower().replace('_', ' ') if planted else 'no brewable crop'} "
                                  f"this season: a plot of {spare[0].lower().replace('_', ' ')} too (another drink)", 4))
        did.append("crops")
    if fruit_now:
        did.append("fruit")                       # the drink rule brews the fruit this cycle
    if not did:
        notes.append(f"{n} citizens are upset at drinking the same booze"
                     + (f" ({kinds} kind(s) in store)" if isinstance(kinds, int) else "")
                     + ": no fruit to brew and no second brewable crop to plant; a caravan's drink would help")


def drink_known_short_s(s: dict, cfg: dict) -> bool:
    from planner_industry import drink_known_short
    return drink_known_short(s, cfg)


def _comfort_rules(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.104.157) The small daily miseries the stress census found
    (Teacheroar, 1 Nov: 75 citizens upset at having no shoes, 63 of 150
    barefoot, the worst cause; 149 drank without a cup): shoes for the
    barefoot (DFHack's tailor only replaces worn-out clothes), made in pairs
    at the leather works (else of cloth at the clothier's); free cups in
    store (the taverns keep theirs in their own chests)."""
    causes = stress_causes(s)
    if causes:
        notes.append("what stresses the fort most (28 days): " + "; ".join(
            f"{THOUGHT_WORDS.get(c.get('thought'), c.get('thought'))} ({c.get('citizens')} citizens"
            + (f", {c['children']} of them children" if c.get("children") else "") + ")"
            for c in causes[:5]))
    cl = _d(_d(s.get("needs")).get("clothing"))
    if not cl:
        return
    st, b = _d(s.get("stocks")), _d(s.get("buildings"))
    citizens = max(1, int(cl.get("citizens") or _d(s.get("dwarves")).get("total") or 1))
    barefoot = int(_d(cl.get("without")).get("shoes") or 0)
    free_shoes = cl.get("free_shoes")
    if barefoot >= max(3, citizens * cfg["barefoot_share"]) and isinstance(free_shoes, int):
        # free ones only (none where no dwarf can walk or still in a workshop),
        # and not boots: civilians never put armour on themselves
        boots = int(_d(_d(cl.get("free_shoes_detail")).get("kinds")).get("ITEM_SHOES_BOOTS") or 0)
        waiting = int(_d(_d(cl.get("free_shoes_detail")).get("place")).get("workshop") or 0)
        pairs = barefoot - (max(0, free_shoes - boots) + waiting) // 2
        recipe = None
        if int(st.get("leather") or 0) >= 10 and _has_shop(b, "Leatherworks"):
            recipe, what = "leather_shoes", "leather shoes"
        elif int(st.get("cloth") or 0) >= 10 and _has_shop(b, "Clothiers"):
            recipe, what = "cloth_shoes", "cloth shoes"
        if pairs <= 0:
            notes.append(f"{barefoot} citizens are barefoot though {free_shoes} shoes lie free in store")
        elif recipe is None:
            notes.append(f"{barefoot} citizens are barefoot and there's no leather or cloth (or no leather works or "
                         "clothier's) to make shoes")
        elif not queued(s, {"leather_shoes", "cloth_shoes"}):
            n = min(cfg["shoes_batch"], pairs)
            upset = _cause_citizens(s, "NoShoes")
            proposals.append(Proposal("comfort", {"type": "work_order", "recipe": recipe, "amount": n},
                                      f"{barefoot} of {citizens} citizens are barefoot"
                                      + (f" ({upset} upset by it lately)" if upset else "")
                                      + f" and the tailor only replaces worn-out clothes: make {n} pair(s) of {what}",
                                      4, True))
    free_cups = cl.get("free_cups")
    cupless = _cause_citizens(s, "DrinkWithoutCup")
    want = max(10, -(-citizens // cfg["citizens_per_free_cup"]))
    # cups made but still in the workshop (the finished goods piles full): more
    # storage, not more cups (the storage rule counts them)
    waiting = unstored_cups(s)
    # (0.104.165) waited for only while the finished goods piles are short of room:
    # with room they aren't coming back (Teacheroar, 1 Nov: 34 cups in two halls for
    # hours with 79 of 107 tiles free, 137 drinking without a cup, none made)
    fg = _d(_d(_d(s.get("logistics")).get("storage")).get("finished_goods"))
    tiles, used = int(fg.get("tiles") or 0), int(fg.get("used") or 0)
    room = tiles > 0 and used / tiles < cfg["store_full_share"]
    stuck = waiting if room else 0
    if waiting and not room and cupless >= citizens * cfg["cupless_share"]:
        notes.append(f"{cupless} citizens drank without a cup lately and {waiting} cups lie off the stockpiles "
                     "(in workshops or halls; dwarves only drink from cups on a stockpile): finished goods storage first")
    elif stuck and cupless >= citizens * cfg["cupless_share"]:
        notes.append(f"{stuck} cups lie in the halls though the finished goods piles have room "
                     f"({used} of {tiles} tiles used): not counted; new ones are made")
    _cups_home_rule(cl, cupless, proposals, notes)       # (0.104.168)
    if isinstance(free_cups, int):
        free_cups = max(0, free_cups - stuck)
    if (isinstance(free_cups, int) and not (waiting and not room) and free_cups < want
            and cupless >= citizens * cfg["cupless_share"]
            and _has_shop(b, "Craftsdwarfs") and not queued(s, {"stone_mugs", "wooden_cups"})):
        wood = int(st.get("wood") or 0)
        cups = stone_short(s, cfg["stone_low"]) and wood >= 20
        n = min(cfg["cups_batch"], want - free_cups)
        proposals.append(Proposal("comfort", {"type": "work_order", "recipe": "wooden_cups" if cups else "stone_mugs",
                                              "amount": n},
                                  f"{cupless} citizens drank without a cup lately and {free_cups} cups are free: make {n} "
                                  + ("wooden cups (no stone to spare)" if cups else "stone mugs"), 5, True))


# (0.104.168) the bridge's reasons a free cup off the piles stays where it lies
CUP_WHY_WORDS = {"location": "kept by a location (a tavern's own)", "pile_refuses": "no finished goods pile takes cups",
                 "pile_refuses_material": "the piles refuse their material",
                 "pile_refuses_quality": "the piles refuse their quality",
                 "links_only": "the piles that take them take from links only",
                 "no_room": "the piles that take them are full",
                 "unreachable": "where no citizen walks", "should_haul": "nothing in the way (waiting for a hauler)",
                 "in_container": "in a bin or barrel (hauled with it)", "unknown": "unread"}


def _cups_home_rule(cl: dict, cupless: int, proposals: list, notes: list) -> None:
    """(0.104.168) Teacheroar, 1 Nov: 34 used cups lay in a dining hall and a
    meeting hall for hours while the finished goods piles had room and 137
    drank without a cup. The bridge's census says why each free cup off the
    piles stays (`free_cups_detail.why`); what the AI can fix it does itself
    (`accept_cups`: the pile with the most room takes the cups no pile takes,
    forbidden cups in a hall unforbidden), the rest is said."""
    cd = _d(cl.get("free_cups_detail"))
    why = {k: int(v) for k, v in _d(cd.get("why")).items() if isinstance(v, int) and v > 0}
    if why:
        locs = {k: v for k, v in _d(cd.get("why_locations")).items() if isinstance(v, int)}

        def part(k: str, v: int) -> str:
            extra = ""
            if k == "location" and locs:
                extra = " (" + ", ".join(f"{n} in a {str(t).lower().replace('inn_tavern', 'tavern')}"
                                         for t, n in sorted(locs.items())) + ")"
            return f"{CUP_WHY_WORDS.get(k, k)}{extra}: {v}"
        notes.append("why the loose cups stay off the piles: "
                     + "; ".join(part(k, v) for k, v in sorted(why.items(), key=lambda kv: -kv[1])))
    refused = sum(why.get(k, 0) for k in ("pile_refuses", "pile_refuses_material", "pile_refuses_quality"))
    forbidden = int(cd.get("forbidden_in_halls") or 0)
    if refused:
        proposals.append(Proposal("cups_home", {"type": "accept_cups"},
                                  f"{refused} loose cup(s) no finished goods pile takes"
                                  + (f" ({cupless} citizens drank without a cup lately)" if cupless else "")
                                  + ": the pile with the most room is set to take them", 4))
    elif forbidden and cupless:
        proposals.append(Proposal("cups_home", {"type": "accept_cups"},
                                  f"{forbidden} cup(s) lie forbidden in the halls and {cupless} citizens drank "
                                  "without a cup lately: unforbidden", 5))


def _shelter_supply_rule(s: dict, memory, proposals: list, notes: list) -> None:
    """(0.105.36, D5) The AI shelter short of drink or food at its last fill
    (the bridge's drink_short, no_water, no_food): with the alarm on, it is
    made again over the fort as it is now once a day, taking in drink and
    food brought inside since and the left-out drink and food tiles (fill_shelter
    takes them back when short); with the alarm off, said, as it is filled
    again when the AI next sounds the alarm."""
    sup = _d(getattr(memory, "shelter_supply", None))
    short = [str(sup[k]) for k in ("no_water", "drink_short", "no_food") if sup.get(k)]
    if not short or not isinstance(sup.get("tick"), int):
        return
    what = "; ".join(short)
    if s.get("civ_alert") is True:
        now = abs_tick(s)
        if now - sup["tick"] >= TICKS_PER_DAY:
            proposals.append(Proposal("shelter_supply", {"type": "refresh_shelter"},
                                      f"the alarm is on and {what}: the shelter is made again over the fort as it "
                                      "is now, to take in the drink and food brought inside since", 1))
        else:
            notes.append(f"the alarm is on and {what}: the AI makes the shelter again each day to take in "
                         "drink and food")
    else:
        notes.append(f"{what} (at its last fill): the AI fills it again, with what drink and food is inside "
                     "then, when it next sounds the alarm")


def _people_rules(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.104.159) Health and people: a soldier who has had a baby goes home
    (the baby is carried into every fight; the fill never drafts mothers, but
    one drafted before her baby came stayed), one a cycle, never a squad
    leader; and what the fort is sick with, by name (the health report's
    syndromes), said in the log."""
    mil = _d(s.get("military"))
    mothers = [m for m in _l(mil.get("soldier_mothers")) if isinstance(m, dict) and m.get("id") is not None]
    for m in mothers:
        if m.get("leader"):
            notes.append(f"{m.get('name')} leads a squad and has a baby (it is carried into every fight): "
                         "the AI leaves a squad leader in place")
            continue
        proposals.append(Proposal("mothers", {"type": "squad_release", "unit_id": m["id"], "mother": True},
                                  f"{m.get('name')} has a baby, carried into every fight: out of her squad", 3))
        break
    # (0.104.159) miasma, where and from what (the census' worst stress at
    # Teacheroar, 136 of 150 disgusted: meat rotting by a stair, z160-162)
    hz = _d(s.get("hazards"))
    spots = [c for c in _l(hz.get("miasma_spots")) if isinstance(c, dict)]
    if spots:
        c = spots[0]
        rot = {str(k): int(v) for k, v in _d(c.get("rotting")).items() if isinstance(v, int)}
        what = ", ".join(f"{n} {k.lower().replace('_', ' ')}" for k, n in sorted(rot.items(), key=lambda kv: -kv[1]))
        notes.append(f"miasma: {hz.get('miasma')} clouds, the worst at x{c.get('x')} y{c.get('y')} z{c.get('z')}"
                     + (f" ({c.get('zone') or c.get('building')})" if c.get("zone") or c.get("building") else "")
                     + (f", rotting near it: {what}" if what else "")
                     + (" by a refuse pile" if c.get("refuse_pile") is not None else ""))
    h = _d(s.get("health"))
    names = {str(k): int(v) for k, v in _d(h.get("syndrome_names")).items() if isinstance(v, int)}
    if names:
        top = sorted(names.items(), key=lambda kv: (-kv[1], kv[0]))[:4]
        notes.append(f"{h.get('syndromes')} citizens have a syndrome: " + ", ".join(f"{k} ({n})" for k, n in top)
                     + (f"; {h.get('infected')} walk about with infected wounds" if h.get("infected") else ""))


def _needs_rules(s: dict, cfg: dict, proposals: list, rules_: dict | None = None, young: bool = False) -> None:
    """Needs met without a new room: crafting (DFHack's idle-crafting at every
    Craftsdwarf's workshop, more of them when many want to craft), things to
    own (a free trinket given), drink (a brewing order), good meals (fine
    meals at the kitchen). Each once enough dwarves are distracted by it."""
    nd = s.get("needs")
    if not isinstance(nd, dict) or "error" in nd:
        return
    rules_ = rules_ or {}
    at = cfg["needs_build_at"]
    b = s["buildings"]
    _quick_location_rule(s, cfg, proposals, rules_)
    ic = _d(nd.get("idle_crafting"))
    craft = unmet(s, "CraftObject")
    shops = nd.get("craft_shops")
    if (craft >= cfg["needs_note_at"] and _has_shop(b, "Craftsdwarfs") and nd.get("idle_crafting") is not None
            and (not ic.get("workshops") or (isinstance(shops, int) and ic.get("workshops", 0) < shops))):
        proposals.append(Proposal("needs_craft", {"type": "idle_crafting"},
                                  f"{craft} dwarves are distracted for want of making something: "
                                  "let idle dwarves craft for themselves at every Craftsdwarf's workshop", 5))
    # more workshops for it: one for every craft_shop_per dwarves who want to craft
    # (0.104.137) one for every craft_shop_per wanting to craft, up to one per
    # craft_shop_citizens dwarves: a fixed 8 held Teacheroar's 221 dwarves (118
    # badly wanting to craft) at the 8 it had
    cit_ = int(_d(s.get("dwarves")).get("total") or 0)
    want_shops = min(max(cfg["craft_shops_max"], -(-cit_ // cfg["craft_shop_citizens"])),
                     1 + craft // cfg["craft_shop_per"])
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    # (0.104.141) past the open-level cap while many want to craft or to own
    # (Teacheroar: 11 wanted, 8 stood, never asked: 4 levels open of 2)
    extra_slots = 2 if max(craft, unmet(s, "AcquireObject")) >= 2 * cfg["craft_shops_at"] else 0
    if (isinstance(shops, int) and craft >= cfg["craft_shops_at"] and shops < want_shops and not young
            and len(open_) < (_d(s.get("projects")).get("max_open") or 2) + extra_slots
            and not _workshops_busy(open_)):
        k = want_shops - shops
        proposals.append(Proposal("needs_shops", {"type": "start_project", "kind": "workshops",
                                                  "shops": ["Craftsdwarfs"] * k,
                                                  # (review) the builder's own cap lets an urgent level past it
                                                  **({"urgent": True} if len(open_) >= (_d(s.get("projects")).get("max_open") or 2) else {})},
                                  f"{craft} dwarves want to craft and {shops} Craftsdwarf's workshop(s) serve "
                                  f"them: build {k} more (idle dwarves craft there for themselves)", 6))
    # things to own: a free trinket each; crafts made when there are none
    acq = unmet(s, "AcquireObject")
    # (0.103.10) Be extravagant is met by wearing an item with a quality
    # modifier (DF wiki, Needs): while dwarves want it, the trinkets made are
    # jewellery to wear (amulets, bracelets, rings, earrings, in turn), not
    # figurines (Enxah: 13 badly, nothing answered it)
    ext = unmet(s, "BeExtravagant")
    jewel = JEWEL_RECIPES[(game_day(s) // 3) % len(JEWEL_RECIPES)]
    making = queued(s, {"stone_crafts", "wood_crafts", "bone_crafts", *JEWEL_RECIPES})
    ordered = False
    # (0.104.122) wooden crafts while stone is short (Teacheroar: 2 usable
    # boulders, stone rings ordered every few hours, cancelled after 15 days
    # as "made in wood instead" and ordered again; 228 wanting something to own)
    wood = int(_d(s.get("stocks")).get("wood") or 0)
    in_wood = stone_short(s, cfg["stone_low"]) and wood >= cfg["wood_crafts_min_logs"]
    if acq >= cfg["needs_note_at"] and rules_.get("give_trinkets", True) and isinstance(nd.get("trinkets"), int):
        # (0.104.137) given and made in amounts the fort's size asks (a fixed 25
        # and 20, made only once none were left, against 166 wanting at 221)
        if nd["trinkets"] > 0:
            give = min(50, max(cfg["trinkets_per_cycle"], acq // 4))
            proposals.append(Proposal("needs_trinkets", {"type": "give_trinkets", "max": give},
                                      f"{acq} dwarves are distracted for want of something to own: give them "
                                      f"trinkets ({nd['trinkets']} free rings, amulets, figurines...)", 5))
        if nd["trinkets"] < max(1, acq // 4) and _has_shop(b, "Craftsdwarfs") and not making:
            r = "wood_crafts" if in_wood else jewel if ext >= cfg["needs_note_at"] else "stone_crafts"
            n = min(cfg["trinket_order_max"], max(20, acq // 2))
            proposals.append(Proposal("trinket_orders", {"type": "work_order", "recipe": r, "amount": n},
                                      f"{acq} dwarves want something to own and {nd['trinkets']} trinkets are free: "
                                      + ("make stone crafts" if r == "stone_crafts" else
                                         f"make wooden crafts (no stone to spare; {wood} logs)" if r == "wood_crafts" else
                                         f"make stone {r.split('_', 1)[1]}s to wear ({ext} want finery too)"), 5, True))
            ordered = r != "wood_crafts"
        # (0.104.141) a second order beside a slow one, in a material the
        # masons don't want: the butchers' bones, else wood (Teacheroar: one
        # ring order at a time, ~15 of 20 made in 28 days, 156 badly wanting)
        elif nd["trinkets"] < max(1, acq // 4) and _has_shop(b, "Craftsdwarfs") and making:
            kinds_q = [r_ for r_ in ("stone_crafts", "wood_crafts", "bone_crafts", *JEWEL_RECIPES) if queued(s, {r_})]
            bones = int(nd.get("bones") or 0)
            wood_free = wood - int(_d(s.get("dwarves")).get("total") or 0) * cfg["wood_per_dwarf"]
            # (0.105.24) not while a strange mood waits for a bone it can't find
            alt = ("bone_crafts" if bones >= cfg["bone_crafts_min"] and "bone_crafts" not in kinds_q
                   and "bone" not in mood_waits(s)
                   else "wood_crafts" if wood_free >= cfg["wood_crafts_min_logs"] and "wood_crafts" not in kinds_q
                   else None)
            if alt and len(kinds_q) < cfg["trinket_parallel"]:
                n = min(cfg["trinket_parallel_max"], max(15, acq // 4))
                proposals.append(Proposal("trinket_orders", {"type": "work_order", "recipe": alt, "amount": n},
                                          f"{acq} dwarves want something to own, {nd['trinkets']} trinkets are free and "
                                          f"{making} wait on the benches: {n} "
                                          + (f"bone crafts beside them ({bones} bones)" if alt == "bone_crafts"
                                             else f"wooden crafts beside them ({wood} logs)"), 5, True))
    if (not ordered and ext >= cfg["needs_note_at"] and rules_.get("give_trinkets", True)
            and isinstance(nd.get("trinkets"), int) and nd["trinkets"] < ext):
        if not stone_short(s, 10) and _has_shop(b, "Craftsdwarfs") and not making:
            proposals.append(Proposal("needs_finery", {"type": "work_order", "recipe": jewel, "amount": min(20, ext)},
                                      f"{ext} dwarves are distracted for want of finery (something of quality to "
                                      f"wear) and {nd['trinkets']} trinkets are free: make stone "
                                      f"{jewel.split('_', 1)[1]}s (a skilled crafter's are of quality)", 5, True))
        elif stone_short(s, 10) and _has_shop(b, "MetalsmithsForge"):
            # (0.104.137) wooden crafts aren't worn: jewellery in metal at the forge
            # (precious first, else copper) while stone is short
            import planner_industry as _pi
            metal = _pi.precious_metal(s, cfg)
            bars = _d(_d(_d(s.get("military")).get("gear")).get("all_bars"))
            if not metal and int(bars.get("COPPER") or 0) >= cfg["finery_metal_bars"]:
                metal = "COPPER"
            mj = "metal_" + jewel.split("_", 1)[1]
            if metal and not queued(s, {"metal_amulet", "metal_bracelet", "metal_ring", "metal_earring"}):
                proposals.append(Proposal("needs_finery", {"type": "work_order", "recipe": mj,
                                                           "amount": min(10, max(3, ext // 8)),
                                                           "material": f"INORGANIC:{metal}"},
                                          f"{ext} dwarves are distracted for want of finery and no stone is "
                                          f"spare: make {metal.lower()} {mj.split('_', 1)[1]}s to wear at the forge", 5, True))
    # (0.105.26) no needs_drink rule: the drink rule ordered first unless the
    # stock was below zero, so it almost never fired (the player: removed)
    pop = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    meals_pd = (_d(s.get("stocks")).get("prepared_meals") or 0) / pop
    sup = _d(s.get("supplies"))
    if "good_meals" in sup:
        # (0.83) a good meal is one worth over 20 (or a preferred food): the
        # count of meals says nothing (region2: 38-46 meals a dwarf, 57
        # distracted for want of a good one), so lavish meals while the good
        # ones are few, whatever the stock of plain ones (to a hard ceiling)
        good_pd = (sup.get("good_meals") or 0) / pop
        if (unmet(s, "EatGoodMeal") >= at and _has_shop(b, "Kitchen") and good_pd < cfg["good_meals_pd"]
                and meals_pd < cfg["meals_hard_max_pd"] and not queued(s, {"prepare_lavish_meal"})):
            # (0.103.8) as many as there are dwarves wanting one, up to 20: 5
            # every 3 days fed a few of Enxah's 14 (the good ones came and
            # went 60 -> 0) while 8 broke down
            n = max(5, min(cfg["lavish_meals_max"], unmet(s, "EatGoodMeal")))
            proposals.append(Proposal("needs_meal", {"type": "work_order", "recipe": "prepare_lavish_meal", "amount": n},
                                      f"{unmet(s, 'EatGoodMeal')} dwarves are distracted for want of a good meal "
                                      f"and {sup.get('good_meals') or 0} of {sup.get('meal_servings') or 0} meals are "
                                      "worth over 20: cook lavish meals", 5, True))
    # (0.103.14) good meals come from a skilled cook: while the store is full
    # and none are worth over 20, only the best cooks work the kitchens
    # (Enxah: 0 of 1892 servings good, lavish ones cooked by anyone); any
    # cook again once the store runs down
    ck = _d(sup.get("cooks"))
    if isinstance(ck.get("kitchen_min"), int) and isinstance(ck.get("best"), int):
        want = min(20, max(cfg["good_cook_min"], ck["best"] - 2)) if ck["best"] >= cfg["good_cook_min"] else 0
        # (0.105.8) at least two free cooks must clear the bar (the bridge's
        # able_skills: adults in no squad with the labour, best first): one
        # cook alone is pulled to other work and the lavish meals stood at the
        # kitchen for weeks (the six forts: 17-37 stuck-order notes each)
        able = [int(x) for x in _l(ck.get("able_skills")) if isinstance(x, (int, float))]
        if want and "able_skills" in ck:
            second = able[1] if len(able) >= 2 else 0
            want = min(want, second) if second >= cfg["good_cook_min"] else 0
            if ck["kitchen_min"] > 0 and (len(able) < 2 or able[1] < ck["kitchen_min"]) and ck["kitchen_min"] <= ck["best"]:
                proposals.append(Proposal("good_cooks", {"type": "kitchen_skill", "min_level": want},
                                          f"the kitchens take only cooks of skill {ck['kitchen_min']}+ and fewer than two "
                                          f"free cooks are that good ({', '.join(map(str, able[:3])) or 'none'}): "
                                          + (f"down to {want}+" if want else "any cook again"), 2))
                ck = None                                # (no second proposal below)
        if ck is None:
            pass
        elif ck["kitchen_min"] > ck["best"]:
            # (0.104.19) nobody left who may cook: the best cook died or left
            # (Enxah: kitchens at 9+, the best now 7; the lavish meals stuck 33
            # days and asked for as Needs you)
            proposals.append(Proposal("good_cooks", {"type": "kitchen_skill", "min_level": want},
                                      f"the kitchens take only cooks of skill {ck['kitchen_min']}+ and the best now is "
                                      f"{ck['best']}: nobody can cook; "
                                      + (f"down to {want}+" if want else "any cook again"), 2))
        elif (want and ck["kitchen_min"] < want and unmet(s, "EatGoodMeal") >= at
                and (sup.get("good_meals") or 0) / pop < cfg["good_meals_pd"] and meals_pd >= cfg["good_cook_store_pd"]):
            proposals.append(Proposal("good_cooks", {"type": "kitchen_skill", "min_level": want},
                                      f"{unmet(s, 'EatGoodMeal')} dwarves want a good meal, {round(meals_pd)} meals a "
                                      f"dwarf are stored and none is worth over 20: only cooks of skill {want}+ "
                                      f"(the best is {ck['best']}) cook, so the meals are worth more", 4))
        elif ck["kitchen_min"] > 0 and meals_pd < cfg["good_cook_release_pd"]:
            proposals.append(Proposal("good_cooks", {"type": "kitchen_skill", "min_level": 0},
                                      f"only {round(meals_pd, 1)} meals a dwarf stored: any cook may cook again", 3))
    if ("good_meals" not in sup and unmet(s, "EatGoodMeal") >= at and _has_shop(b, "Kitchen")
            and meals_pd < cfg["needs_meal_max_pd"]
            and not queued(s, {"prepare_fine_meal", "prepare_lavish_meal"})):
        proposals.append(Proposal("needs_meal", {"type": "work_order", "recipe": "prepare_fine_meal", "amount": 5},
                                  f"{unmet(s, 'EatGoodMeal')} dwarves are distracted for want of a good meal: "
                                  "cook fine meals", 5, True))


def ghost_work_blocked(s: dict, memory=None, slabs: bool = True) -> list[str]:
    """(0.105.26) Why the ghosts' memorial slabs or coffins can't be made
    now, in words (empty when nothing stands in the way): no stone the masons
    may use, no mason's workshop or nobody with the labour, an order the game
    refused or that got stuck and was cancelled. A slab order that couldn't
    be made sat silently while the ghosts walked."""
    ai_slabs = slabs                    # the AI makes the slabs (autoslab engraves them)
    d, su, b = _d(s.get("dead")), _d(s.get("supplies")), _d(s.get("buildings"))
    ghosts = int(d.get("ghosts") or 0)
    if ghosts <= 0:
        return []
    slabs, ms = su.get("slabs"), su.get("memorial_slabs")
    slabs_short = (ai_slabs and isinstance(slabs, int) and slabs < ghosts
                   and not (isinstance(ms, int) and ms > 0))
    coffins = sum(int(_d(_d(p.get("furnish")).get("waiting")).get("Coffin") or 0)
                  for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict))
    if not slabs_short and coffins <= 0:
        return []
    out = []
    what = " and ".join((["memorial slabs"] if slabs_short else []) + (["coffins"] if coffins > 0 else []))
    if slabs_short and stone_short(s, 1):
        out.append("no stone the masons may use: waiting for quarried stone to make them")
    elif coffins > 0 and stone_short(s, 1) and int(_d(s.get("stocks")).get("wood") or 0) <= 0:
        out.append("no stone or wood for coffins")
    if (b.get("workshops") is not None and not _has_shop(b, "Masons")
            and not (coffins > 0 and not slabs_short and _has_shop(b, "Carpenters"))):
        out.append("no mason's workshop")
    if any(isinstance(w, dict) and w.get("labor") == "MASON" and int(w.get("holders") or 0) == 0
           for w in _l(_d(s.get("labor")).get("waiting"))):
        out.append("nobody outside the squads has the mason labour")
    if memory is not None:
        now = abs_tick(s)
        for key, r in _d(getattr(memory, "refusals", None)).items():
            if (str(key).split(":", 1)[0] in ("slabs", "coffins") and isinstance(r, dict)
                    and int(r.get("n") or 0) > 0 and isinstance(r.get("until"), int) and now < r["until"]):
                out.append(f"the game refused it ({str(r.get('why') or 'no reason given')[:80]})")
                break
        sc = _d(getattr(memory, "stuck_cancelled", None))
        for rec in ["stone_slab"] + [k for k in sc if str(k).endswith("_coffin")]:
            t = _d(sc.get(rec)).get("tick")
            if isinstance(t, int) and 0 <= now - t < 28 * TICKS_PER_DAY:
                out.append(f"the {rec.replace('_', ' ')} order got stuck and was cancelled "
                           f"{(now - t) // TICKS_PER_DAY} day(s) ago")
                break
    return [f"{ghosts} ghost(s) wait for {what}, which can't be made now: {w}" for w in out[:1]] + out[1:]


def _dead_notes(s: dict, notes: list, proposals: list | None = None, rules_: dict | None = None,
                memory=None) -> None:
    d = s["dead"]
    if d.get("ghosts"):
        who = ", ".join(_l(d.get("ghost_names"))[:3])
        who = f" ({who})" if who else ""
        autoslab = _d(s.get("tools")).get("autoslab")
        if not (rules_ or {}).get("engrave_slabs", True):
            # (0.105.35) the player's own switch: said, not handed back
            notes.append(f"{d['ghosts']} ghost(s) haunt the fort{who}: the AI buries the bodies it can and "
                         "engraves no memorial slabs while the Rules switch for them is off")
        elif autoslab is None:
            # DF engraves a slab only for a named dead dwarf, a job no work order
            # makes; DFHack's autoslab makes it, and this DFHack has none
            ask_player(notes, f"{d['ghosts']} ghost(s) haunt the fort{who}: the AI can't engrave their memorial "
                              "slabs (DFHack's autoslab, which makes that job, isn't to be had here); meanwhile it "
                              "buries the bodies it can in the tombs")
        else:
            # DFHack's autoslab engraves the slabs; it needs blank ones in stock
            slabs = _d(s.get("supplies")).get("slabs")
            ms = _d(s.get("supplies")).get("memorial_slabs")
            # (0.104.42) slabs made but held: forbidden, or their building's
            # job suspended (Enxah: 9 of 9 ghosts' slabs so, 25 dead of fright)
            stuck = [g for g in _l(d.get("ghost_list")) if isinstance(g, dict)
                     and (_d(g.get("slab_at")).get("forbid") or _d(g.get("slab_job")).get("suspended")
                          or (g.get("slab") == "loose" and _d(g.get("slab_at")).get("reach") is False))]
            if proposals is not None and stuck:
                murderous = sum(1 for g in stuck if g.get("kind") == "MurderousGhost")
                proposals.append(Proposal("slabs_free", {"type": "free_slabs"},
                                          f"{len(stuck)} ghost(s)' memorial slabs are made but held (forbidden, or "
                                          "their building's job suspended)"
                                          + (f", {murderous} of them murderous" if murderous else "")
                                          + ": unforbid them and resume the work", 1))
            if proposals is not None and isinstance(ms, int) and ms > 0:
                # (0.103.16) autoslab engraves them but nobody puts them up
                proposals.append(Proposal("slabs", {"type": "place_slabs", "max": min(20, ms)},
                                          f"{d['ghosts']} ghost(s){who} walk the fort and {ms} engraved memorial "
                                          "slab(s) lie unbuilt: put them up so the dead rest", 3))
            elif (proposals is not None and isinstance(slabs, int) and slabs < d["ghosts"]
                    and queued(s, {"stone_slab"}) == 0 and stone_short(s, 1)):
                # (0.104.14) no stone the masons may use: an order would only
                # stand still and be cancelled as stuck (the quarry comes first)
                pass                     # (0.105.26) said in Needs you below (ghost_work_blocked)
            elif (proposals is not None and isinstance(slabs, int) and slabs < d["ghosts"]
                    and masons_jammed(s)):
                # (0.104.32) autoslab's engrave jobs fill the mason's list
                # waiting for the very slabs a work order can't get on to it:
                # blank slabs straight on the bench, room made by lifting some
                n = min(5, d["ghosts"] - slabs)
                proposals.append(Proposal(
                    "slabs", {"type": "bench_jobs", "kind": "slab", "count": n, "make_room": True},
                    f"{d['ghosts']} ghost(s){who} need memorial slabs, {slabs} blank, and autoslab's "
                    f"{masons_jammed(s)} engrave jobs fill the mason's bench waiting for them: put {n} blank "
                    "slab(s) straight on the bench", 3))
            elif (proposals is not None and isinstance(slabs, int) and slabs < d["ghosts"]
                    and queued(s, {"stone_slab"}) == 0):
                proposals.append(Proposal(
                    "slabs", {"type": "work_order", "recipe": "stone_slab", "amount": d["ghosts"] - slabs + 1},
                    f"{d['ghosts']} ghost(s){who} need memorial slabs and there are {slabs} blank ones", 3, True))
    # (0.105.26) a slab or coffin for the ghosts that can't be made: said, with why
    if d.get("ghosts"):
        ai_slabs = _d(s.get("tools")).get("autoslab") is not None and (rules_ or {}).get("engrave_slabs", True)
        blocked = ghost_work_blocked(s, memory, slabs=ai_slabs)
        if blocked:
            # (0.105.35) what the AI can mend, it does (a mason's workshop, the
            # mason labour); stone comes from the quarry rule: a note, no Needs you
            text = "; ".join(blocked)
            open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
            if proposals is not None and "no mason's workshop" in text and not _workshops_busy(open_):
                proposals.append(Proposal("ghost_masons", {"type": "start_project", "kind": "workshops",
                                                           "shops": ["Masons"]},
                                          f"{d['ghosts']} ghost(s) wait for slabs or coffins and the fort has no "
                                          "mason's workshop: build one", 3))
            if proposals is not None and "mason labour" in text:
                proposals.append(Proposal("ghost_mason", {"type": "assign_labor", "job": "MASON", "count": 1},
                                          f"{d['ghosts']} ghost(s) wait for slabs or coffins and nobody outside "
                                          "the squads has the mason labour: the best at it given it", 3))
            notes.append(text + " (the AI builds what is missing; the quarry rule brings stone)")
    # (0.104.15) why the unburied wait (Enxah: 104 bodies, 7 free tombs, a season)
    why = _d(d.get("why"))
    # (0.104.17) the free tombs turn citizens away (automatic burial off):
    # Enxah's 7 all did, so 104 bodies lay with room for 7 of them
    if d.get("unburied") and (d.get("free_tombs_no_citizens") or 0) > 0 and proposals is not None:
        proposals.append(Proposal("burial", {"type": "allow_burial"},
                                  f"{d['unburied']} dead unburied and {d['free_tombs_no_citizens']} of the "
                                  f"{d.get('free_tombs')} free tombs have automatic burial of citizens off: switch "
                                  "it on in the AI's tombs", 2))
    if d.get("unburied") and d.get("free_tombs") and why:
        # (0.105.27) the bridge reads the standing order right now (it read
        # false always before): with "forbid your dead" on, the game forbids
        # each body as it falls and the AI unforbids the ones with a free tomb,
        # as before. The order itself is left as the player set it
        order_on = bool(d.get("forbid_own_dead"))
        if (why.get("forbidden") or 0) - (why.get("unreachable") or 0) > 0 and proposals is not None:
            proposals.append(Proposal("burial", {"type": "unforbid_dead", "max": 20},
                                      f"{why['forbidden']} of the fort's {d['unburied']} unburied dead are forbidden "
                                      f"where they lie and {d['free_tombs']} tomb(s) stand free: unforbid them so "
                                      "they are buried"
                                      + (" (the game's standing order \"forbid your dead\" forbids each body as "
                                         "it falls)" if order_on else ""), 3))
        if why.get("unreachable"):
            notes.append(f"{why['unreachable']} of the unburied dead lie where the dwarves can't walk"
                         + (f" ({why.get('outside')} outside)" if why.get("outside") else ""))
    # (0.105.35) the tombs rule digs a tomb level with its coffins (planner_building): a note
    if d.get("unburied") and not d.get("free_tombs"):
        notes.append(f"{d['unburied']} citizen bodies wait for burial and there is no free tomb: the AI digs a "
                     "tomb level for them")
    if d.get("loose_coffins") and not d.get("free_tombs"):
        notes.append(f"{d['loose_coffins']} coffins aren't in a tomb zone, so nobody is buried in them: the AI's "
                     "next tomb level places them")


# Offices the AI fills itself (lua/ai-nobles.lua), most needed first: from 20
# citizens DF does a work order only after the manager validates it.
AI_OFFICES = ("MANAGER", "BOOKKEEPER", "CHIEF_MEDICAL_DWARF", "BROKER", "SHERIFF", "CAPTAIN_OF_THE_GUARD")


def _society_notes(s: dict, traits: dict, citizens: int, cfg: dict, notes: list,
                   proposals: list | None = None) -> None:
    so = s["society"]
    names = {"MANAGER": "manager (work orders)", "BOOKKEEPER": "bookkeeper (stock counts)",
             "BROKER": "broker (trading)", "CHIEF_MEDICAL_DWARF": "chief medical dwarf (the hospital)",
             "SHERIFF": "sheriff (justice)", "CAPTAIN_OF_THE_GUARD": "captain of the guard (justice)"}
    raw = [v for v in _l(so.get("vacant")) if isinstance(v, str)]
    # the sheriff becomes the captain of the guard as a fort grows: one office
    if "SHERIFF" in raw and "CAPTAIN_OF_THE_GUARD" in raw:
        raw.remove("CAPTAIN_OF_THE_GUARD")
    elif "SHERIFF" in raw:
        # the captain of the guard has replaced the sheriff: nothing to fill
        raw.remove("SHERIFF")
    # (a captain's post vacant while the sheriff serves: the post a growing
    # fort adds; it leads the fort guard and is filled like any other office)
    appoint = player_rules(s)["appoint_nobles"] and proposals is not None
    if appoint:
        for code in AI_OFFICES:
            if code in raw:
                urgent = code == "MANAGER" and citizens >= 15
                proposals.append(Proposal("appoint", {"type": "appoint", "office": code},
                                          f"nobody is {names[code]}"
                                          + (": from 20 dwarves no work order is done without one" if urgent else "")
                                          + ": appoint the best-suited dwarf", 1 if urgent else 3))
        raw = [v for v in raw if v not in AI_OFFICES]
    vacant = [names.get(v, v.lower()) for v in raw]
    if vacant:
        # (0.105.35) a note: the player's switch (or no proposals this cycle), not a task for them
        notes.append("nobody holds these offices: " + ", ".join(vacant)
                     + (" (the AI appoints only the manager, bookkeeper, broker, chief medical dwarf, sheriff and "
                        "captain of the guard)" if appoint
                        else " (the AI's appointing is switched off on the Rules tab)"
                        if not player_rules(s)["appoint_nobles"] else ""))
    if so.get("starving") or so.get("parched"):
        who = ", ".join(_l(so.get("hungry_names"))[:3])
        # (0.105.35) what the AI does (no longer a check for the player): a dwarf in
        # bed drinks only what one with the labour brings; the AI's burrows
        # let out the thirsty and the hungry at each report
        if so.get("parched") and proposals is not None:
            proposals.append(Proposal("care_feed", {"type": "assign_labor", "job": "FEED_WATER_CIVILIANS",
                                                    "count": 2},
                                      f"{so.get('parched')} dwarves are parched: two more given the labour "
                                      "that brings food and water to the bedridden", 2))
        notes.append(f"{so.get('starving', 0)} dwarves are starving and {so.get('parched', 0)} parched"
                     + (f" ({who})" if who else "") + ": the AI's food and drink rules keep the stocks up and "
                       "its burrows let the thirsty out"
                     + ("; two more dwarves bring water to the bedridden" if so.get("parched") else ""))
    if so.get("grazers_unpastured") and not player_rules(s)["pasture_animals"]:
        # (0.105.35) the player's own switch: said, not handed back
        notes.append(f"{so['grazers_unpastured']} grazing animals have no pasture and will starve: the AI "
                     "leaves pastures alone while its pasture switch is off on the Rules tab")


# --- (0.104.168) complaints nobody heard; vermin ---------------------------------

# DF's reasons a citizen goes to someone in charge (history_event_reason, the
# subthought of UnableComplain / Complained)
COMPLAINT_WORDS = {"insufficient_work": "too little work", "work_request": "asking for work",
                   "make_weapon": "asking for weapons", "vent_at_boss": "venting",
                   "cry_on_boss": "crying on someone in charge"}


def _cause(s: dict, thought: str) -> dict:
    return next((c for c in stress_causes(s) if c.get("thought") == thought), {})


def _about(c: dict) -> list:
    """A cause's `about` tally (bridge 0.104.168), the most first: [(word, n)]."""
    return sorted(((str(k), int(v)) for k, v in _d(c.get("about")).items()
                   if isinstance(v, (int, float)) and not isinstance(v, bool)), key=lambda kv: (-kv[1], kv[0]))


def _complaint_notes(s: dict, cfg: dict, notes: list) -> None:
    """(0.104.168) Citizens "unable to complain" (DF's COMPLAINT_UNREGISTERED:
    nobody in charge to hear them). DF sends a citizen's complaint to the
    noble who meets the workers (the mayor, the expedition leader before one;
    MEET_WORKERS), in their office when they have one; one meeting at a
    time. Teacheroar, 1 Nov: 24 citizens a month unheard while the mayor
    held meeting after meeting (11 waiting). The AI can't add a second
    mayor (the position is elected, one a fort) nor shorten DF's meetings:
    it gives the mayor an office whatever Deference says, keeps nobles out
    of its recreation burrow (no office in it), and says here why they went
    unheard: venting eases as the fort's stress does; "too little work"
    with work for the idle hands."""
    c = _cause(s, "UnableComplain")
    n = int(c.get("citizens") or 0)
    if n < cfg["complaint_note_min"]:
        return
    about = _about(c)
    words = "; ".join(f"{COMPLAINT_WORDS.get(k, k.replace('_', ' '))} {v}" for k, v in about[:3])
    text = f"{n} citizens couldn't lodge a complaint lately" + (f" ({words})" if words else "")
    offices = _d(_d(s.get("offices")).get("offices"))
    holder = _complaint_holder(s)
    if offices and holder is None:
        notes.append(text + ": the fort has no mayor (or expedition leader) to hear them; DF holds the election")
        return
    name = str(holder[1][0]) if holder else ""
    who = f"the {holder[0].lower().replace('_', ' ')}, {name}" if holder else "the mayor"
    acts, waiting, vis = mayor_meetings(s, name.split(" ")[0] if name else "")
    busy = (f", is in meetings back to back ({waiting} waiting)" if acts and waiting
            else ", is in a meeting" if acts else ", is the only one DF sends them to")
    # (0.105.24) visitors take the mayor's time too: B and F (2-5 Nov) met
    # poets, dancers and bards (who come to ask to stay) as often as citizens
    if vis:
        busy += (f"; {vis} of those meetings are with visitors (performers and scholars asking to stay: "
                 "fewer come with a lower Outsiders, or the tavern, temples and library shut to visitors)")
    no_office = any(isinstance(x, dict) and "office" in _l(x.get("needs"))
                    and x.get("office") in ("MAYOR", "EXPEDITION_LEADER")
                    for x in _l(_d(s.get("noble_rooms")).get("nobles")))
    work = sum(v for k, v in about if k in ("insufficient_work", "work_request"))
    vent = sum(v for k, v in about if k in ("vent_at_boss", "cry_on_boss"))
    if no_office:
        tail = "; with no office of their own to meet them in (the AI gives one when a free office stands)"
    elif work > vent:
        tail = "; most were asking for work: work for the idle hands meets it"
    else:
        tail = "; it eases as the fort's stress does (DF has one mayor, one meeting at a time)"
    notes.append(f"{text}: {who}{busy}{tail}")


def _vermin_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.104.168) Citizens upset at being "accosted by" vermin they hate
    (DF's NEAR_HATED_VERMIN; Teacheroar, 1 Nov: 15-16 a month, stress 25-50
    each). A cat (a vermin hunter, HUNTS_VERMIN) loose in the fort catches
    them; DFHack's autobutcher, which the AI turns on for big herds
    (0.104.158), culls cats with the rest and spares only the named, pets
    and those up for adoption. So a few cats are kept from the butcher by a
    nickname, one per `citizens_per_mouser`; with none, it's said."""
    c = _cause(s, "AnnoyedVermin")
    n = int(c.get("citizens") or 0)
    if n < cfg["vermin_note_min"]:
        return
    kinds = ", ".join(f"{k.lower().replace('_', ' ')} {v}" for k, v in _about(c)[:3])
    text = f"{n} citizens were upset lately by vermin they hate" + (f" ({kinds})" if kinds else "")
    vh = _d(_d(s.get("needs")).get("vermin_hunters"))
    if not vh:
        notes.append(text)
        return
    citizens = int(_d(s.get("dwarves")).get("total") or 0)
    want = max(cfg["mousers_min"], min(cfg["mousers_max"], citizens // max(1, cfg["citizens_per_mouser"])))
    total, loose, kept = int(vh.get("n") or 0), int(vh.get("loose") or 0), int(vh.get("kept") or 0)
    if total == 0:
        notes.append(text + ": the fort has no cat or other vermin hunter (buy cats from a caravan)")
    elif loose == 0:
        notes.append(text + f": the fort's {total} cat(s) are all caged, where they hunt nothing")
    elif kept < want and loose > kept and proposals is not None:
        k = min(want, loose)
        proposals.append(Proposal("vermin", {"type": "keep_mousers", "count": k},
                                  text + f": {kept} of the {loose} loose cat(s) are safe from the butcher; keep {k} "
                                  "(nicknamed Mouser, which autobutcher spares) to hunt them", 5))


__all__ += ["COMPLAINT_WORDS", "_complaint_notes", "_vermin_rule", "OFFICE_FIRST"]
