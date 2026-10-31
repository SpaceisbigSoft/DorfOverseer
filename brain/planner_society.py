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

__all__ = ["_doctor_patient_rule", "MOOD_WORKSHOPS", "PETITION_KINDS", "petition_orders_wanted", "_petition_rules", "_jail_size_rule", "_convict_rule", "_break_fights_rule", "_sync_offices_rule", "patient_waits", "_health_rules", "TANTRUM_KEEP", "note_tantrums", "_noble_rooms_rule", "outsider_orders", "NEED_ADVICE", "JEWEL_RECIPES", "_recreation_rule", "_stress_care", "_needs_notes", "_location_supply_rules", "POST_LABORS", "STAFF_POSTS", "STAFF_MAX", "_traction_rule", "_wish_words", "_wish_met", "wish_key", "_location_petition_rules", "_meeting_notes", "_grandeur_rule", "_location_value_rule", "_staff_rule", "_quick_location_rule", "_needs_rules", "_mood_rules", "mood_item_text", "_mood_materials", "_dead_notes", "AI_OFFICES", "_society_notes"]


# A crafting mood's skill -> the workshop (or furnace) the dwarf must claim.
MOOD_WORKSHOPS = {
    "WOODCRAFT": "Craftsdwarfs", "STONECRAFT": "Craftsdwarfs", "BONECARVE": "Craftsdwarfs",
    "CARPENTRY": "Carpenters", "MASONRY": "Masons", "CUTGEM": "Jewelers", "ENCRUSTGEM": "Jewelers",
    "FORGE_WEAPON": "MetalsmithsForge", "FORGE_ARMOR": "MetalsmithsForge",
    "FORGE_FURNITURE": "MetalsmithsForge", "METALCRAFT": "MetalsmithsForge",
    "CLOTHESMAKING": "Clothiers", "WEAVING": "Loom", "LEATHERWORK": "Leatherworks",
    "TANNER": "Tanners", "GLASSMAKER": "GlassFurnace", "BOWYER": "Bowyers", "MECHANICS": "Mechanics",
}


PETITION_KINDS = ("performer", "scholar", "monster_hunter", "mercenary", "sanctuary", "citizenship")


def petition_orders_wanted(s: dict, cfg: dict) -> dict:
    """(0.87) What DF's standing orders should answer residency and
    citizenship petitions with (1 accept, 0 ask): performers (the tavern's
    music and stories), scholars (the library's writing), those seeking
    sanctuary; monster hunters from a Militarism of 0, mercenaries from 30;
    citizenship while the fort is under its population target. Residents
    live at the tavern and do only the work they came for; mercenaries and
    monster hunters never ask to be citizens (DF wiki, Petition)."""
    traits = _d(_d(s.get("settings")).get("traits"))
    mil = traits.get("militarism", 0) or 0
    citizens = int(_d(s.get("dwarves")).get("total") or 0)
    o = outsider_orders(traits)          # (0.96) Outsiders: guests from -30, nobody at -50 or lower
    g = o["guests"]
    return {"performer": g, "scholar": g, "sanctuary": g,
            "monster_hunter": 1 if mil >= cfg["petition_hunters_militarism"] and not o["closed"] else 0,
            "mercenary": 1 if mil >= cfg["petition_mercenaries_militarism"] and not o["closed"] else 0,
            "citizenship": 1 if (citizens < growth_target(s, cfg) - cfg["petition_citizen_margin"]
                                 and not o["closed"]) else 0}


def _petition_rules(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.87) Petitions DF waits on an answer for (the log: citizenship and
    guildhall petitions "ignored" again and again): with the Rules switch on,
    DF's own standing orders answer residency and citizenship petitions
    (petition_orders_wanted); the AI changes them only when they differ.
    Petitions waiting are noted by kind; temples and guildhalls stay yours
    (0.89: the AI answers and builds them itself, _location_petition_rules)."""
    pt = s.get("petitions")
    if not isinstance(pt, dict) or "error" in pt:
        return
    pending = [e for e in _l(pt.get("pending")) if isinstance(e, dict)]
    if pending:
        kinds = {}
        for e in pending:
            k = e.get("type") or "?"
            kinds[k] = kinds.get(k, 0) + 1
        vamp = [e.get("name") for e in pending if e.get("vampire")]
        notes.append("petitions waiting for an answer: " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items()))
                     + (f" (a vampire among them: {', '.join(str(v) for v in vamp)})" if vamp else ""))
    orders = _d(pt.get("orders"))
    if not player_rules(s).get("accept_visitors", True):
        return
    if not orders:
        # (live, 0.87.0: DFHack 53.16-r3 doesn't expose these globals; newer
        # df-structures have them for 53.16, so a DFHack update turns this on)
        if pending:
            notes.append("this DFHack can't reach DF's petition standing orders: petitions to stay wait for "
                         "you (a newer DFHack lets the AI answer them)")
        return
    if any(orders.get(k) not in (0, 1) for k in PETITION_KINDS):
        notes.append("DF's petition standing orders hold values the AI doesn't know: left alone")
        return
    want = petition_orders_wanted(s, cfg)
    change = {k: v for k, v in want.items() if orders.get(k) != v}
    if change:
        what = ", ".join(f"{'accept' if v else 'ask about'} {k.replace('_', ' ')}" for k, v in change.items())
        proposals.append(Proposal("petitions", {"type": "petition_orders", "orders": change},
                                  f"petitions to stay: {what} (DF's standing orders answer them)", 6))


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
    sentenced = int(crimes["sentenced_all"] if isinstance(crimes.get("sentenced_all"), int)
                    else _d(crimes.get("flags")).get("sentenced") or 0)
    now = abs_tick(s)
    w = memory.convict_watch if isinstance(memory.convict_watch, dict) else {}
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
            w["until"] = now + cfg["convict_rest_days"] * 1200
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


def patient_waits(s: dict, memory, now: int) -> dict:
    """Since when each patient with a treatment asked has waited: the booked
    day, or now for a new one (0.104.78: only while a treatment is asked)."""
    patients = [p for p in _l(_d(s.get("health")).get("patients")) if isinstance(p, dict) and p.get("id") is not None]
    seen = {str(p["id"]) for p in patients if _l(p.get("needs"))}
    # (0.104.133) every patient waiting, not the 30 listed: one off the list
    # lost the day their wait began and started again from "now"
    ids = _d(s.get("health")).get("waiting_ids")
    if isinstance(ids, list):
        seen |= {str(i) for i in ids if isinstance(i, int)}
    since = {k: v for k, v in _d(getattr(memory, "patient_since", None)).items() if k in seen and isinstance(v, int)}
    for k in seen:
        since.setdefault(k, now)
    return since


def _health_rules(s: dict, memory, cfg: dict, notes: list) -> None:
    """Phase 12 (health over years): each patient's wait is tracked
    (memory.patient_since); one who has waited health_wait_days, or an
    infected wound, is said, with why it may be (no hospital, no chief
    medical dwarf, no soap). The care itself is DF's doctors' work: the AI
    stocks the hospital and appoints the chief medical dwarf elsewhere."""
    h = _d(s.get("health"))
    if not h or h.get("error"):
        return
    now = abs_tick(s)
    patients = [p for p in _l(h.get("patients")) if isinstance(p, dict) and p.get("id") is not None]
    # (0.104.78) the wait runs only while a treatment waits: a patient listed
    # for years with an old infection and nothing asked (Enxah's chief medical
    # dwarf, "6215 days") counted from the first day he was listed
    since = patient_waits(s, memory, now)     # (0.104.81) booked in note_cycle: plan() reads memory only
    hospital = _d(_d(s.get("locations")).get("count")).get("HOSPITAL", 0)
    doctor = not ("CHIEF_MEDICAL_DWARF" in _l(_d(s.get("society")).get("vacant")))
    soap = _d(s.get("supplies")).get("soap") or 0
    why = []
    if not hospital:
        why.append("there is no hospital")
    if not doctor:
        why.append("nobody is chief medical dwarf")
    long = []
    for p in patients:
        if str(p["id"]) not in since:
            continue
        days = (now - since[str(p["id"])]) // TICKS_PER_DAY
        # (0.88.3) only those with a treatment still waiting (live: three dwarves
        # with infected wounds, up and working with nothing left to do, were
        # "waiting 538 days for care" as Needs you)
        if days >= cfg["health_wait_days"] and _l(p.get("needs")):
            long.append((days, p))
    long.sort(key=lambda x: -x[0])
    if long:
        who = "; ".join(f"{p.get('name') or p['id']} {d} days"
                        + (f" (needs {', '.join(map(str, _l(p.get('needs'))[:3]))})" if p.get("needs") else "")
                        for d, p in long[:3])
        n_long = len(long)
        if isinstance(_d(s.get("health")).get("waiting_ids"), list):    # (0.104.133) every one, not the listed
            n_long = sum(1 for k, v in since.items() if (now - v) // TICKS_PER_DAY >= cfg["health_wait_days"])
        ask_player(notes, f"{n_long} dwarves have waited a long time for care: {who}"
                   + (": " + " and ".join(why) if why
                      else ": check the doctors' labours (diagnose, surgery, suturing, bone setting)"))
    # (0.104.122) the full count (the list stops at 30) and the hospital's own
    # bars (it said "28 ... no soap" with 112 infected and 5 bars kept there)
    n_inf = _d(s.get("health")).get("infected")
    n_inf = n_inf if isinstance(n_inf, int) else sum(1 for p in patients if p.get("infected"))
    hosp = _location(s, "HOSPITAL")
    if hosp is not None:
        soap += int(_d(hosp.get("have")).get("soap") or 0) // LOCATION_UNITS["soap"]
    if n_inf and not soap:
        ask_player(notes, f"{n_inf} dwarves have infected wounds and the fort has no soap "
                   "(wounds are cleaned with soap)")


def _doctor_patient_rule(s: dict, proposals: list) -> None:
    """(0.104.111, the 38-year soak) Teacheroar's surgeon and bone doctor lay
    in the hospital themselves, holding their posts, while five dwarves waited
    450-820 days for care. A hospital post held by a dwarf being treated (in
    the hospital, or waiting for a treatment) is given back; the staffing
    rule then gives it to the best healthy dwarf (wounded ones are passed over
    since 0.104.111). One a cycle."""
    h = _d(s.get("health"))
    sick = {p.get("id"): p for p in _l(h.get("patients"))
            if isinstance(p, dict) and (p.get("in_hospital") or _l(p.get("needs")))}
    if not sick:
        return
    for hosp in _l(h.get("hospital")):
        if not isinstance(hosp, dict) or not isinstance(hosp.get("id"), int):
            continue
        for st in _l(hosp.get("staff")):
            uid = _d(st).get("unit_id")
            if uid in sick:
                p = sick[uid]
                post = str(_d(st).get("post") or "post").lower().replace("_", " ")
                proposals.append(Proposal("doctor_patient", {"type": "vacate_post", "location_id": hosp["id"],
                                                             "unit_id": uid},
                                          f"the hospital's {post}, {p.get('name') or uid}, is a patient"
                                          + (f" (needs {', '.join(map(str, _l(p.get('needs'))[:3]))})"
                                             if _l(p.get("needs")) else "")
                                          + ": the post goes to a healthy dwarf", 2))
                return


TANTRUM_KEEP = 60           # tantrums remembered (each [tick, who])


def note_tantrums(state: dict, memory, events: list) -> int:
    """(0.104.31) Tantrums seen in the game's announcements, one a dwarf a
    day (the game repeats one tantrum in many lines). Returns how many new."""
    now = abs_tick(state)
    day = now // TICKS_PER_DAY
    have = {(int(t[0]) // TICKS_PER_DAY, str(t[1])) for t in memory.tantrums
            if isinstance(t, list) and len(t) == 2 and isinstance(t[0], int)}
    n = 0
    for e in events or []:
        if not isinstance(e, dict) or e.get("kind") != "report" or e.get("topic") != "tantrum":
            continue
        text = " ".join(str(e.get("text") or "").split())
        if "cancels" in text:
            continue                    # "... cancels X: Throwing tantrum." repeats the same one
        who = text.split(" is throwing")[0].split(" throws")[0][:30]
        if (day, who) in have:
            continue
        have.add((day, who))
        memory.tantrums.append([now, who])
        n += 1
    memory.tantrums = [t for t in memory.tantrums if isinstance(t, list) and len(t) == 2][-TANTRUM_KEEP:]
    return n


def _noble_rooms_rule(s: dict, cfg: dict, proposals: list, memory=None) -> None:
    """A noble whose office asks for a bedroom, office, dining room or tomb
    of their own gets a free one (an unhappy noble makes demands); which of
    them by Deference (0.96, noble_room_kinds)."""
    nr = _d(s.get("noble_rooms"))
    free = dict(_d(nr.get("free")))
    kinds_given = noble_room_kinds(_traits(s) if isinstance(s.get("settings"), dict) else {}, memory)
    # (0.100.2) the manager's office first, whatever Deference says: it's
    # where work orders are taken up, not a noble's comfort
    nobles = sorted((n for n in _l(nr.get("nobles")) if isinstance(n, dict)),
                    key=lambda n: n.get("office") != "MANAGER")
    for n in nobles:
        for kind in _l(n.get("needs")):
            given = kind in kinds_given or (kind == "office" and n.get("office") == "MANAGER")
            if given and (free.get(kind) or 0) > 0:
                free[kind] -= 1
                proposals.append(Proposal("noble_rooms", {"type": "give_room", "unit_id": n.get("unit_id"),
                                                          "kind": kind, "name": n.get("name")},
                                          f"{n.get('name')} has no {kind} of their own"
                                          f"{' (dining room)' if kind == 'dining' else ''}: give them a free one", 4))


def outsider_orders(traits: dict) -> dict:
    """Outsiders (closed - welcoming): which petitions to stay DF's standing
    orders may accept: performers, scholars and those seeking sanctuary
    from -30; monster hunters, mercenaries and new citizens never at -50 or
    lower (whatever Militarism and Growth say)."""
    o = traits.get("outsiders", 0) or 0
    guests = 1 if o >= -30 else 0
    closed = o <= -50
    return {"guests": guests, "closed": closed}
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
    then), nor in a fort under `recreation_min_citizens`."""
    if proposals is None or not player_rules(s).get("recreation", True):
        return
    citizens = int(_d(s.get("dwarves")).get("total") or 0)
    if citizens < cfg["recreation_min_citizens"]:
        return
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return
    low = [x for x in worst if x.get("stress") in ("miserable", "very_unhappy") and not x.get("squad")]
    members = int(_d(_d(s.get("society")).get("recreation")).get("members") or 0)
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
    nd = s.get("needs")
    if not isinstance(nd, dict) or "error" in nd:
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
        ask_player(notes, f"the fort agreed to petitions it hasn't kept: {', '.join(want[:4])}. Make a meeting-area "
                          "zone a location of that kind and choose the god or profession in the location screen "
                          "(the Rules switch for building them is off)")
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
        ask_player(notes, f"{n_mis} dwarf(s) are miserable and may throw tantrums (the worst: "
                   + "; ".join(f"{x.get('name')} (missing {', '.join(x.get('unmet') or []) or '?'})"
                               for x in miserable[:3]) + ")")
    elif worst:
        notes.append(f"{n_worst} dwarf(s) very unhappy: "
                     + "; ".join(f"{x.get('name')} (missing {', '.join(x.get('unmet') or []) or '?'})"
                                 for x in worst[:3]))


def _location_supply_rules(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.84) What the tavern, temple and library keep: mugs for the tavern
    (stone, at a Craftsdwarf's workshop); a note for instruments and paper,
    which the AI doesn't make yet."""
    tav = _location(s, "INN_TAVERN")
    if tav is not None:
        short = _location_short(tav, ("goblets", "instruments"))
        if "goblets" in short and _has_shop(s["buildings"], "Craftsdwarfs") and not queued(s, {"stone_mugs", "wooden_cups"}):
            h, w = short["goblets"]
            # (0.104.4) wooden cups while there's no stone (Enxah: mugs ordered and
            # cancelled six times, 0 usable boulders, 233 logs)
            wood = int(_d(s.get("stocks")).get("wood") or 0)
            cups = stone_short(s, cfg["stone_low"]) and wood >= 20
            proposals.append(Proposal("tavern", {"type": "work_order", "recipe": "wooden_cups" if cups else "stone_mugs",
                                                 "amount": min(10, w - h)},
                                      f"the tavern has {h} of the {w} goblets it keeps: make "
                                      + ("wooden cups (no stone to spare)" if cups else "stone mugs"), 6, True))
        # (0.104.4) a tavern keeps its goblets in a chest of its own (its coffer):
        # without one the goblets made never count as the tavern's
        if ("goblets" in short and tav.get("chests") == 0 and _l(tav.get("zones"))
                and isinstance(_l(tav.get("zones"))[0], int)):
            proposals.append(Proposal("tavern_chest", {"type": "place_in_zone", "zone_id": _l(tav["zones"])[0],
                                                       "what": "chest"},
                                      "the tavern has no chest to keep its goblets in: put one in it", 6))
    # (0.104.77) a tavern built before 0.104.76 seats no one beside anyone:
    # while many badly want friends, a chair beside each lone chair (a week
    # apart; the bridge says when every chair has a neighbour)
    cit_t = max(1, int(_d(s.get("dwarves")).get("total") or 0))
    friends_badly = int(_d(_d(_d(s.get("needs")).get("needs")).get("BeWithFriends")).get("badly") or 0)
    if friends_badly >= cit_t * cfg["pair_chairs_friends_share"]:
        taverns = sorted((e for e in _l(_d(s.get("locations")).get("list")) if isinstance(e, dict)),
                         key=lambda e: bool(e.get("over_dining")))      # the proper tavern before the stop-gap
        # (0.104.78) every tavern zone, and the dining halls the stop-gaps lie
        # over, tried in turn by the bridge
        zones = [z for e in taverns if e.get("type") == "INN_TAVERN"
                 for z in _l(e.get("zones")) if isinstance(z, int)]
        if zones:
            proposals.append(Proposal("pair_chairs", {"type": "pair_chairs", "zones": zones[:6],
                                                      "max": min(20, max(5, int(friends_badly // 4)))},   # (0.104.137)
                                      f"{friends_badly} dwarves badly want friends and dwarves talk only with "
                                      "those beside them: a chair beside each lone chair in the taverns", 5))
    # (0.104.8) instruments for the tavern and the temples: DFHack's
    # `instruments` tool orders a hand-held one with all its parts (each world
    # invents its own instruments); a month between orders (the tool's orders
    # aren't the AI's, so they can't be counted as queued)
    lack = []
    chest_asked = False
    for e in _l(_d(s.get("locations")).get("list")):
        if isinstance(e, dict) and e.get("type") in ("INN_TAVERN", "TEMPLE"):
            sh = _location_short(e, ("instruments",))
            if "instruments" in sh:
                # (0.104.67) a location keeps its instruments in a chest of its
                # own: without one none count as its own (Enxah's second temple:
                # 0 of 5, no chest, 105 instrument orders since 15:12)
                if (e.get("chests") == 0 and e.get("type") == "TEMPLE" and _l(e.get("zones"))
                        and isinstance(_l(e.get("zones"))[0], int)):
                    if not chest_asked:
                        proposals.append(Proposal("temple_chest", {"type": "place_in_zone",
                                                                   "zone_id": _l(e["zones"])[0], "what": "chest"},
                                                  "a temple has no chest to keep its instruments in: put one in it", 5))
                        chest_asked = True
                    continue
                lack.append((e.get("type"), *sh["instruments"]))
    # (0.104.69) the instruments tool's orders (a reaction MAKE_ENT<n> IN...):
    # one still open holds the next; more than 3 not begun are trimmed to one
    # (Enxah: 31 open, ~150 instruments asked, the carpenters' slots full)
    ins_orders = [o for o in _l(s.get("orders")) if isinstance(o, dict)
                  and re.match(r"MAKE_ENT\d+ IN", str(o.get("reaction") or "")) and int(o.get("amount_left") or 0) > 0]
    unbegun = [o for o in ins_orders if int(o.get("amount_left") or 0) >= int(o.get("amount_total") or 0)]
    if len(unbegun) > 3:
        proposals.append(Proposal("instrument_orders", {"type": "trim_instrument_orders", "keep": 1},
                                  f"{len(ins_orders)} instrument orders wait ({len(unbegun)} not begun): keep one", 3))
    if ins_orders:
        lack = []
    if lack and _has_shop(s["buildings"], "Craftsdwarfs"):
        missing = sum(w - h for _, h, w in lack)
        where = ", ".join(f"{'the tavern' if t == 'INN_TAVERN' else 'a temple'} {h} of {w}" for t, h, w in lack[:3])
        proposals.append(Proposal("instruments", {"type": "order_instrument", "amount": max(1, min(5, missing))},
                                  f"instruments kept: {where}: order hand-held ones with their parts "
                                  "(DFHack's instruments tool)", 6))
    lib = _location(s, "LIBRARY")
    if lib is not None:
        short = _location_short(lib, ("paper",))
        if "paper" in short or not lib.get("books"):
            notes.append(f"the library has {lib.get('books') or 0} books and "
                         f"{short.get('paper', (0, 0))[0]} of {short.get('paper', (0, 0))[1]} sheets of paper "
                         "(writing needs paper and scribes)")
        # (0.104.79) a library keeps its paper in a chest of its own, as a
        # temple its instruments (Enxah's: 0 of 10, no chest, parchment made)
        if ("paper" in short and lib.get("chests") == 0 and _l(lib.get("zones"))
                and isinstance(_l(lib.get("zones"))[0], int)):
            proposals.append(Proposal("library_chest", {"type": "place_in_zone", "zone_id": _l(lib["zones"])[0],
                                                        "what": "chest"},
                                      "the library has no chest to keep its paper in: put one in it", 5))


# (0.87.3) the labours each post needs (lua/ai-society.lua POST_LABORS)
POST_LABORS = {"DOCTOR": ("DIAGNOSE", "SURGERY", "BONE_SETTING", "SUTURING", "DRESSING_WOUNDS"),
               "DIAGNOSTICIAN": ("DIAGNOSE",), "SURGEON": ("SURGERY", "SUTURING"), "BONE_DOCTOR": ("BONE_SETTING",)}

# (0.84) posts at locations the AI fills, in this order, and how many of each
STAFF_POSTS = {"HOSPITAL": ("DIAGNOSTICIAN", "DOCTOR", "SURGEON", "BONE_DOCTOR"), "LIBRARY": ("SCRIBE",),
               "INN_TAVERN": ("TAVERN_KEEPER",)}
STAFF_MAX = {"SCRIBE": 2, "TAVERN_KEEPER": 2, "DIAGNOSTICIAN": 2, "DOCTOR": 2, "SURGEON": 2, "BONE_DOCTOR": 2}


def _traction_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.88) A hospital wants a traction bench for broken bones that need
    traction (DF wiki, Hospital; region2's had beds, chests and a table, no
    bench). A free bench goes into the hospital zone with the most beds; with
    none, one is made at a Mechanic's workshop from a table, a mechanism and a
    rope or chain, the missing part ordered first."""
    sup = _d(s.get("supplies"))
    if "traction_benches" not in sup:
        return
    for h in _l(_d(s.get("health")).get("hospital")):
        zones = [z for z in _l(_d(h).get("zones")) if isinstance(z, dict) and z.get("id") is not None]
        if not zones:
            continue
        have = sum(max(int(z.get("traction") or 0), int(z.get("traction_planned") or 0)) for z in zones)
        if have >= cfg["hospital_traction"]:
            continue
        zone = max(zones, key=lambda z: int(z.get("beds") or 0))
        if int(sup.get("traction_benches") or 0) > 0:
            proposals.append(Proposal("traction", {"type": "place_in_zone", "zone_id": zone["id"],
                                                   "what": "traction_bench"},
                                      "the hospital has no traction bench (broken bones that need traction "
                                      "wait without one): put one in", 5))
            return
        if queued(s, {"traction_bench"}):
            return
        b = s["buildings"]
        if not _has_shop(b, "Mechanics"):
            notes.append("a traction bench for the hospital needs a Mechanic's workshop")
            return
        st = s["stocks"]
        part = None
        if not int(sup.get("tables") or 0) and not queued(s, {"wooden_table", "stone_table"}):
            part = ("stone_table", "a table")
        elif not int(st.get("mechanisms") or 0) and not queued(s, {"mechanisms"}):
            part = ("mechanisms", "a mechanism")
        elif not int(sup.get("ropes") or st.get("chains") or 0) and not queued(s, {"cloth_rope"}):
            part = ("cloth_rope", "a rope") if int(st.get("cloth") or 0) else None
            if part is None:
                notes.append("a traction bench for the hospital waits for a rope or chain (no cloth for a rope)")
                return
        if part:
            proposals.append(Proposal("traction_parts", {"type": "work_order", "recipe": part[0], "amount": 1},
                                      f"a traction bench for the hospital needs {part[1]}: make one", 6, True))
        else:
            proposals.append(Proposal("traction_parts", {"type": "work_order", "recipe": "traction_bench", "amount": 1},
                                      "the hospital has no traction bench: make one at the Mechanic's workshop "
                                      "(a table, a mechanism, a rope)", 6, True))
        return


def _wish_words(w: dict) -> str:
    tier = int(w.get("tier") or 1)
    if w.get("loc") == "GUILDHALL":
        what = ("a grand guildhall" if tier >= 2 else "a guildhall") + " for the " + \
            str(w.get("profession") or "?").lower().replace("_", " ") + "s"
    else:
        what = ("a temple complex" if tier >= 2 else "a temple") + " to " + str(w.get("deity") or "their god")
    return what


def _wish_met(s: dict, w: dict) -> dict | None:
    """The fort's location that answers a petition's wish, if it has one."""
    for e in _l(_d(s.get("locations")).get("list")):
        if not isinstance(e, dict):
            continue
        if w.get("loc") == "GUILDHALL" and e.get("type") == "GUILDHALL" and e.get("profession") == w.get("profession"):
            return e
        if w.get("loc") == "TEMPLE" and e.get("type") == "TEMPLE" and (
                (w.get("religion") is not None and e.get("religion") == w.get("religion"))
                or (w.get("deity_hf") is not None and e.get("deity_hf") == w.get("deity_hf"))):
            return e
    return None


def wish_key(w: dict) -> str:
    """(0.102.2) What a location petition asks for, the same for a repeat."""
    return "|".join(str(w.get(k)) for k in ("loc", "profession", "religion", "deity_hf"))


def _location_petition_rules(s: dict, cfg: dict, proposals: list, notes: list, rules_: dict,
                             memory=None) -> None:
    """(0.89, phase 12b) Petitions for a temple or guildhall: the AI agrees to
    the ones it will build (a temple or guildhall, not yet the tier-2 temple
    complex or grand guildhall unless the fort cares how it looks or is
    devout), one at a time, then builds a grand hall dedicated to that god or
    profession, all of it engraved, before the agreement's year runs out
    (DF wiki, Guildhall: 2000 of zone value makes a guildhall). The Rules
    switch "Build the temples and guildhalls dwarves ask for" turns it off."""
    pt = _d(s.get("petitions"))
    pending = [p for p in _l(pt.get("pending")) if isinstance(p, dict) and p.get("type") == "Location"]
    agreed = [w for w in _l(pt.get("agreed")) if isinstance(w, dict)]
    if not (pending or agreed):
        return
    if not rules_.get("answer_locations", True):
        return
    traits = _traits(s)
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    # (0.97) the Temple level switch, and the Maintain goal (no temple), cover
    # petition temples too: those are left to you; guildhalls go on
    no_temples = (not _d(rules_.get("levels")).get("temple", True)) or rules_.get("fort_goal") == "maintain"
    if no_temples and any(w.get("loc") == "TEMPLE" for w in pending + agreed):
        notes.append("temple petitions are left to you: " + ("the fort's goal is Maintain"
                                                             if rules_.get("fort_goal") == "maintain"
                                                             else "the Temple level is off on the Rules tab"))
        pending = [w for w in pending if w.get("loc") != "TEMPLE"]
        agreed = [w for w in agreed if w.get("loc") != "TEMPLE"]
    # agreed: build what isn't there yet
    unbuilt = [w for w in agreed if not _wish_met(s, w)]
    # (0.92) a hall still being dug whose own wish something else answered
    # meanwhile (the player's own guildhall): given to the next unbuilt wish
    for p in open_:
        ded = _d(p.get("dedication"))
        if p.get("kind") != "temple" or not ded or p.get("phase") != "dig":
            continue
        own = {"loc": "GUILDHALL" if ded.get("profession") else "TEMPLE", "profession": ded.get("profession"),
               "deity_hf": ded.get("deity_hf"), "religion": ded.get("religion")}
        if not _wish_met(s, own):
            continue
        nxt = [w for w in unbuilt if not (w.get("profession") and w.get("profession") == ded.get("profession"))]
        if not nxt:
            continue
        w = nxt[0]
        action = {"type": "retarget_hall", "project_id": p.get("id")}
        for k in ("profession", "religion", "deity_hf"):
            if w.get(k) is not None and (k != "deity_hf" or w.get("religion") is None):
                action[k] = w[k]
                break
        if len(action) == 2:
            continue
        proposals.append(Proposal("petition_retarget", action,
                                  f"the hall being dug was for {_wish_words(own)}, which the fort now has: "
                                  f"make it {_wish_words(w)} instead", 4))
        return
    for w in agreed:
        e = _wish_met(s, w)
        need = cfg["location_value_tier2"] if int(w.get("tier") or 1) >= 2 else cfg["location_value_tier1"]
        if e and int(e.get("tier") or 0) < int(w.get("tier") or 1):
            notes.append(f"{_wish_words(w)} (agreed, {w.get('days', '?')} days ago) stands but is worth "
                         f"{e.get('value', '?')} of the {need} it needs: engrave and furnish it")
    if unbuilt and not any(p.get("kind") == "temple" for p in open_):
        w = unbuilt[0]
        action = {"type": "start_project", "kind": "temple", "size": "grand"}
        if w.get("loc") == "GUILDHALL":
            if not w.get("profession"):
                return
            action["profession"] = w["profession"]
        elif w.get("religion") is not None:
            action["religion"] = w["religion"]
        elif w.get("deity_hf") is not None:
            action["deity_hf"] = w["deity_hf"]
        else:
            return
        left = max(0, 336 - int(w.get("days") or 0))
        # (0.104.138) the last 112 days an agreed petition is urgent (a slot of
        # its own); before that it waits for a free slot instead of being
        # refused (Teacheroar: "already 3 unfinished building projects" 11 times
        # while its year ran from 335 days left to 148)
        limit = int(_d(s.get("projects")).get("max_open") or 2)
        if left < 112:
            action["urgent"] = True
        elif len(open_) >= limit:
            notes.append(f"{_wish_words(w)} (agreed) waits for a building slot ({left} days left of the year)")
            return
        proposals.append(Proposal("petition_build", action,
                                  f"the fort agreed to {_wish_words(w)}: build it ({left} days left of the year)",
                                  4 if left < 112 else 5))
    if not pending:
        return
    if young_fort(s, cfg):
        notes.append(f"{len(pending)} petition(s) for a temple or guildhall wait: not while the fort is young")
        return
    if len(unbuilt) >= cfg["location_petitions_open"]:
        return
    for w in pending:
        tier = int(w.get("tier") or 1)
        known = w.get("profession") if w.get("loc") == "GUILDHALL" else (w.get("deity_hf") is not None
                                                                         or w.get("religion") is not None)
        if not known or w.get("loc") not in ("TEMPLE", "GUILDHALL"):
            continue
        if tier >= 2 and not (traits.get("grandeur", 0) > 0 or (w.get("loc") == "TEMPLE" and traits.get("piety", 0) > 0)):
            notes.append(f"a petition asks for {_wish_words(w)}: left to you (a fort that doesn't care for grandeur "
                         "agrees to temples and guildhalls, not their grand tier)")
            continue
        # (0.102.2) the same wish again within a year of agreeing to it (War-hold
        # agreed 120 in a game year, mostly the same halls): DF didn't count the
        # hall the fort already had; agreeing again only makes another promise
        done = _d(getattr(memory, "wishes_agreed", None)).get(wish_key(w))
        if _wish_met(s, w) and isinstance(done, int) and abs_tick(s) - done < TICKS_PER_YEAR:
            notes.append(f"a petition asks again for {_wish_words(w)}, agreed {(abs_tick(s) - done) // TICKS_PER_DAY} "
                         "days ago and standing: left to lapse, not promised twice")
            continue
        if _wish_met(s, w):
            reason = f"a petition asks for {_wish_words(w)}, and the fort has one: agree"
        else:
            reason = f"a petition asks for {_wish_words(w)}: agree, and build it within the year"
        proposals.append(Proposal("petition_answer", {"type": "answer_petition", "id": w.get("id"), "accept": True,
                                                      "wish": wish_key(w)},
                                  reason, 6))
        return


def _meeting_notes(s: dict, notes: list) -> None:
    """(0.91) A diplomat's or the liaison's meeting screen waits for the
    player's answers (DF's meeting screen): said in Needs you, with who is
    meeting whom. The AI doesn't answer meetings yet (a probe first)."""
    m = _d(s.get("meetings"))
    if not m:
        return
    screen = str(m.get("screen") or "")
    acts = [a for a in _l(m.get("activities")) if isinstance(a, dict)]
    who = "; ".join(f"{a.get('actor')} with {a.get('noble')}" for a in acts[:2]) or "a diplomat"
    if any(w in screen.lower() for w in ("meeting", "diplomacy")):
        # (0.94.1) only the meeting screen itself, which holds the game until
        # answered, is a Needs you
        ask_player(notes, f"DF's meeting screen is open and waits for your answers ({who}): the AI doesn't "
                          "answer meetings yet (in an unattended run it leaves the screen after 10 minutes)")
    elif int(m.get("popups") or 0) > 0:
        # (0.94.1) a queued meeting popup doesn't hold the game (region2 ran
        # on through days of them): a note, not a Needs you
        notes.append(f"a meeting waits to be shown in DF ({who}); the game runs on meanwhile")
    elif acts:
        notes.append("meetings under way: " + "; ".join(
            f"{a.get('actor')} with {a.get('noble')}" + (f" (tree quota {a['tree_quota']})" if a.get("tree_quota") else "")
            for a in acts[:3]))


def _grandeur_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.102.6) A grand fort (Grandeur 50+) dresses its halls: the least
    valuable temple, tavern, library or guildhall below 2000 x (1 + Grandeur
    /100) gets a statue at a time (one made of stone when none is free).
    Not while young or short of food and drink. War-hold at Grandeur 60 built
    nothing grand in a game year: a mature fort saw nothing missing."""
    traits = _traits(s)
    g = traits.get("grandeur", 0) or 0
    if g < cfg["grandeur_dress_at"] or young_fort(s, cfg):
        return
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    if (_d(s.get("stocks")).get("drink") or 0) < citizens * cfg["good_times_drink_per_dwarf"] \
            or food_per_dwarf(s) < cfg["good_times_food_per_dwarf"]:
        return
    want = int(cfg["location_value_tier1"] * (1 + g / 100))
    halls = [e for e in _l(_d(s.get("locations")).get("list")) if isinstance(e, dict)
             and e.get("type") in ("TEMPLE", "INN_TAVERN", "LIBRARY", "GUILDHALL") and _l(e.get("zones"))
             and int(e.get("value") or 0) < want]
    if not halls:
        return
    e = min(halls, key=lambda e: int(e.get("value") or 0))
    what = str(e.get("type")).lower().replace("inn_", "").replace("_", " ")
    if int(_d(s.get("supplies")).get("statues") or 0) > 0:
        proposals.append(Proposal("grandeur", {"type": "place_in_zone", "zone_id": _l(e["zones"])[0], "what": "statue"},
                                  f"a grand fort (Grandeur {int(g):+d}): the {what} is worth {e.get('value') or 0} of "
                                  f"the {want} it should be: put a statue in it", 6))
    elif not queued(s, {"stone_statue"}) and not stone_short(s, 10):
        proposals.append(Proposal("grandeur", {"type": "work_order", "recipe": "stone_statue", "amount": 3},
                                  f"a grand fort (Grandeur {int(g):+d}): the {what} is worth {e.get('value') or 0} of "
                                  f"the {want} it should be: make statues for it", 6, True))


def _location_value_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.90) A hall built for a petition counts only once its zone is worth
    its tier (2000 a temple or guildhall, 10000 the grand tier). Once its
    project is finished (engraving adds the most), a statue at a time goes
    into its zone until it is, made of stone when none is free."""
    agreed = [w for w in _l(_d(s.get("petitions")).get("agreed")) if isinstance(w, dict)]
    if not agreed:
        return
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    if any(p.get("kind") == "temple" for p in open_):
        return
    sup = _d(s.get("supplies"))
    for w in agreed:
        e = _wish_met(s, w)
        if not e or not _l(e.get("zones")):
            continue
        tier = int(w.get("tier") or 1)
        need = cfg["location_value_tier2"] if tier >= 2 else cfg["location_value_tier1"]
        value = int(e.get("value") or 0)
        if int(e.get("tier") or 0) >= tier or value >= need:
            continue
        if int(sup.get("statues") or 0) > 0:
            proposals.append(Proposal("location_value", {"type": "place_in_zone", "zone_id": _l(e["zones"])[0],
                                                         "what": "statue"},
                                      f"{_wish_words(w)} is worth {value} of the {need} it needs: put a statue in it", 5))
        elif not queued(s, {"stone_statue"}):
            proposals.append(Proposal("location_value", {"type": "work_order", "recipe": "stone_statue", "amount": 3},
                                      f"{_wish_words(w)} is worth {value} of the {need} it needs: make statues for it",
                                      6, True))
        return


def _staff_rule(s: dict, cfg: dict, proposals: list) -> None:
    """Vacant posts at the fort's locations (the bridge's `locations.list`):
    a hospital's diagnostician, doctor, surgeon and bone doctor first (urgent
    while someone needs care: region2's patients waited 130 days), then a
    library's scribes and a tavern's keeper; one post a cycle (ai-society
    staff_location picks the dwarf best at the trade)."""
    patients = int(_d(s.get("dwarves")).get("needs_medical_care") or 0)
    # (0.87.3) the hospital's staff without their post's labours (live: the
    # surgeon, bone doctor and doctor the AI seated had none, and a dwarf
    # needing a bone set waited 355 days): given first
    for h in _l(_d(s.get("health")).get("hospital")):
        if not isinstance(h, dict) or h.get("id") is None:
            continue
        short = [st.get("post") for st in _l(h.get("staff")) if isinstance(st, dict)
                 and set(POST_LABORS.get(st.get("post"), ())) - set(_l(st.get("labors")))]
        if short:
            proposals.append(Proposal("staff", {"type": "staff_labors", "location_id": h["id"]},
                                      f"the hospital's {', '.join(str(x).lower().replace('_', ' ') for x in short)} "
                                      "can't do their work (the post's labours are off)"
                                      + (f" and {patients} need care" if patients else "")
                                      + ": turn them on", 2 if patients else 4))
            return
    # (0.85) posts DF hasn't made yet (it makes them when the location's posts
    # screen is opened): the AI makes them as the game does, then fills them.
    # A library's scribes only once it has paper or books (they copy and write).
    order = sorted((e for e in _l(_d(s.get("locations")).get("list")) if isinstance(e, dict)),
                   key=lambda e: list(STAFF_POSTS).index(e.get("type")) if e.get("type") in STAFF_POSTS else 9)
    for e in order:
        if e.get("type") not in STAFF_POSTS or e.get("id") is None:
            continue
        if e["type"] == "LIBRARY" and not (e.get("books") or _d(e.get("have")).get("paper")):
            continue
        missing = [k for k in STAFF_POSTS[e["type"]] if k not in _d(e.get("jobs"))]
        if missing:
            hosp = e["type"] == "HOSPITAL"
            proposals.append(Proposal("staff", {"type": "add_posts", "location_id": e["id"], "posts": missing},
                                      f"the {e['type'].lower().replace('_', ' ')} has no post for "
                                      f"{', '.join(k.lower().replace('_', ' ') for k in missing)}"
                                      + (f" and {patients} need care" if hosp and patients else "")
                                      + ": make the posts (as its location screen does)", 2 if hosp and patients else 5))
            return
    for e in order:
        jobs = _d(e.get("jobs"))
        for post in STAFF_POSTS.get(e.get("type"), ()):
            j = _d(jobs.get(post))
            posts, filled = int(j.get("posts") or 0), int(j.get("filled") or 0)
            if filled < min(posts, STAFF_MAX.get(post, posts)):
                hosp = e.get("type") == "HOSPITAL"
                what = post.lower().replace("_", " ")
                proposals.append(Proposal("staff", {"type": "staff_location", "location_id": e.get("id"), "post": post},
                                          f"the {e.get('type', '').lower().replace('_', ' ')} has no {what}"
                                          + (f" ({filled} of {posts} posts filled)" if filled else "")
                                          + (f" and {patients} need care" if hosp and patients else "")
                                          + f": give the post to the dwarf best at it", 2 if hosp and patients else 5))
                return


def _quick_location_rule(s: dict, cfg: dict, proposals: list, rules_: dict) -> None:
    """(0.102.5) No temple or tavern while dwarves break down for want of
    one: the fort's dining hall becomes one at once (a zone laid over it, no
    digging); the proper hall comes later through the build ladder. Only
    when its level is allowed on the Rules tab and no such level is being
    dug. Enxah, y53: 6 miserable, 7 of 8 longing to pray, every slot on food."""
    loc = _d(s.get("locations"))
    have = loc.get("count") if isinstance(loc.get("count"), dict) else {}
    if "locations" in s.get("_errors", {}) or not _d(_d(s.get("buildings")).get("zones")).get("DiningHall"):
        return
    levels = _d(rules_.get("levels"))
    open_ = {p.get("kind") for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)}
    at = cfg["needs_build_at"]
    for kind, key, needs in (("temple", "TEMPLE", ("PrayOrMeditate",)), ("tavern", "INN_TAVERN", SOCIAL_NEEDS)):
        n = max(unmet(s, k) for k in needs)        # dwarves, not needs summed over them
        if levels.get(kind, True) and not have.get(key) and kind not in open_ and n >= at:
            proposals.append(Proposal("quick_" + kind, {"type": "quick_location", "kind": kind},
                                      f"{n} dwarves are distracted for want of a {'place to pray' if kind == 'temple' else 'tavern'} "
                                      f"and the fort has none: make the dining hall one for now", 3))
            return


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
            alt = ("bone_crafts" if bones >= cfg["bone_crafts_min"] and "bone_crafts" not in kinds_q
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
    recipe = brew_recipe(s)
    # (0.100.1, review) as many brews as there are empty barrels and pots: an
    # order with nowhere to put the drink stood still, was cancelled as stuck,
    # and held all brewing 28 days
    sup_n = _d(s.get("supplies"))
    room = int(sup_n.get("empty_barrels") or 0) + int(sup_n.get("empty_pots") or 0)
    # (0.104.71) nor when the drink rule asks for a brew this cycle: both
    # brewed at once (16:32: 11 and 10) and the extra order was cancelled as
    # stuck ("2 brew orders and this one"), 11 of 61 in 3.5 hours
    brewing_now = any(isinstance(p.action, dict) and p.action.get("recipe") in BREW_RECIPES for p in proposals)
    # (0.104.137) not when drink is already plentiful: the want is for a place
    # to drink with others (taverns: social_shortfall), not more barrels
    # (Teacheroar: 56 badly wanting a drink with 8.7 drinks a dwarf)
    plenty = int(_d(s.get("stocks")).get("drink") or 0) >= cfg["drink_per_dwarf"] * int(_d(s.get("dwarves")).get("total") or 0)
    if (unmet(s, "DrinkAlcohol") >= at and _has_shop(b, "Still") and not queued(s, set(BREW_RECIPES))
            and recipe is not None and room > 0 and not brewing_now and not plenty):
        # (13c) what a still can brew, as the drink rule chooses: this rule
        # ordered fruit brews the drink_fruit rule then cancelled
        proposals.append(Proposal("needs_drink", {"type": "work_order", "recipe": recipe, "amount": min(10, room)},
                                  f"{unmet(s, 'DrinkAlcohol')} dwarves are distracted for want of a drink: brew more",
                                  4, True))
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
        if ck["kitchen_min"] > ck["best"]:
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


def _mood_rules(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """A dwarf in a crafting mood needs the right workshop, then materials;
    without them the dwarf goes insane. Insanity itself is only reported."""
    now = abs_tick(s)
    b = s["buildings"]
    for m in _l(s["moods"].get("list")):
        name, mood = m.get("name") or "a dwarf", m.get("mood")
        if mood == "Baby":
            continue                      # (older bridge) a baby being carried, not a mood
        if not m.get("craft"):
            notes.append(f"{name} has gone {str(mood).lower()}: lost to the fort (this can't be undone)"
                         if mood in ("Melancholy", "Raving", "Berserk") else f"{name}: {mood}")
            continue
        days = (now - memory.moods_seen.get(str(m.get("unit_id")), now)) // TICKS_PER_DAY
        need = MOOD_WORKSHOPS.get(str(m.get("skill")))
        if m.get("workshop"):
            have, want = m.get("items_have"), m.get("items_needed")
            missing = [x for x in _l(m.get("missing")) if isinstance(x, dict)]
            if missing and days >= cfg["mood_wait_days"]:
                _mood_materials(s, name, mood, missing, days, proposals, notes, cfg)
            elif isinstance(have, int) and isinstance(want, int) and have < want and days >= 3:
                notes.append(f"{name}'s {mood.lower()} mood: gathering materials ({have}/{want}) for "
                             f"{days} days; if it stalls, DFHack's showmood says what's missing")
            continue
        if need and not _has_shop(b, need):
            building = _workshops_busy([p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)])
            if building:
                notes.append(f"{name} is in a {mood.lower()} mood and needs a {need}; a workshops level "
                             "is already being built")
            elif need in BUILDABLE_SHOPS:
                proposals.append(Proposal(
                    "mood", {"type": "start_project", "kind": "workshops", "shops": [need], "urgent": True},
                    f"{name} is in a {mood.lower()} mood and needs a {need} workshop, which the fort "
                    "doesn't have; without one they go insane", 1))
            else:
                ask_player(notes, f"{name} is in a {mood.lower()} mood and needs a {need}, which the fort "
                             "doesn't have and the AI can't build: build one, or they go insane")
        elif days >= cfg["mood_claim_days"]:
            ask_player(notes, f"{name} has been in a {mood.lower()} mood for {days} days without claiming a "
                         f"workshop{' (' + need + ')' if need else ''}: is one free and reachable?")


def mood_item_text(x: dict) -> str:
    """'2 cloth (plant)', '1 bar of iron', in words."""
    item = str(x.get("item") or "item").lower().replace("_", " ")
    item = {"skin tanned": "leather", "corpsepiece": "bone or shell", "rough": "rough gem",
            "smallgem": "cut gem", "boulder": "stone", "wood": "log", "blocks": "block"}.get(item, item)
    q = int(x.get("quantity") or 1)
    what = f"{q} {item}" + ("s" if q > 1 and not item.endswith("s") else "")
    if x.get("material"):
        what += f" of {str(x['material']).lower()}"
    kinds = [f for f in _l(x.get("flags")) if f in ("bone", "shell", "metal", "plant", "silk", "leather",
                                                   "yarn", "hard", "glass", "wood")]
    return what + (f" ({', '.join(kinds)})" if kinds else "")


def _mood_materials(s: dict, name: str, mood: str, missing: list, days: int,
                    proposals: list, notes: list, cfg: dict | None = None) -> None:
    """A mood gathering materials for days: order what a recipe can make,
    and say exactly what's still missing (a mood that never gets its
    materials ends in madness)."""
    st = _d(s.get("stocks"))
    ordered, lacking = [], []
    for x in missing:
        item = str(x.get("item") or "")
        flags = set(_l(x.get("flags")))
        recipe = None
        if item == "BLOCKS" and not x.get("material") and not flags & {"metal", "glass", "wood"}:
            recipe = "stone_blocks"
        elif (item == "CLOTH" and st.get("thread") and not flags & {"silk", "yarn"}
              and (thread_plants_here(s) or not wool_route(s))):
            # (0.104.36) not where the thread is all wool: a plant-cloth order
            # then only cancels at the loom, "needs plant thread" (Enxah's
            # weaver's mood, no fibre crop; the cloth comes from a caravan)
            recipe = "weave_plant_cloth"
        if recipe and not queued(s, {recipe}):
            ordered.append(recipe)
            proposals.append(Proposal("mood", {"type": "work_order", "recipe": recipe,
                                               "amount": max(1, min(10, int(x.get("quantity") or 1)))},
                                      f"{name}'s {mood.lower()} mood needs {mood_item_text(x)}: make it", 1, True))
        elif not recipe:
            lacking.append(mood_item_text(x))
    cfg = cfg or PLANNER_CONFIG
    if lacking and days < cfg["mood_lacking_days"]:
        # (0.103.8) the dwarf may still be fetching it: Enxah's fisherdwarf
        # claimed the mason's on day 3, "lacked" rock that day and the next
        # (51 boulders about) and began the work on day 5
        notes.append(f"{name}'s {mood.lower()} mood: still gathering after {days} days, waiting on "
                     f"{', '.join(lacking)}")
    elif lacking:
        ask_player(notes, f"{name}'s {mood.lower()} mood still lacks, after {days} days: {', '.join(lacking)}. "
                   "The fort probably has none the dwarf can reach or use: make it, dig it, buy it from a "
                   "caravan, or unforbid it, or the dwarf goes insane")


def _dead_notes(s: dict, notes: list, proposals: list | None = None, rules_: dict | None = None) -> None:
    d = s["dead"]
    if d.get("ghosts"):
        who = ", ".join(_l(d.get("ghost_names"))[:3])
        who = f" ({who})" if who else ""
        autoslab = _d(s.get("tools")).get("autoslab")
        if autoslab is None or not (rules_ or {}).get("engrave_slabs", True):
            ask_player(notes, f"{d['ghosts']} ghost(s) haunt the fort{who}: bury the body in a coffin, or "
                              "engrave a memorial slab for them at a craftsdwarf's workshop")
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
                notes.append(f"{d['ghosts']} ghost(s) need memorial slabs: waiting for quarried stone to make them")
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
        if d.get("forbid_own_dead"):
            ask_player(notes, f"{d['unburied']} bodies wait for burial and the game's standing order \"forbid your "
                              "dead\" is on, so nobody carries them to the free tombs: switch it off (the Orders "
                              "screen, Forbid)")
        elif (why.get("forbidden") or 0) - (why.get("unreachable") or 0) > 0 and proposals is not None:
            proposals.append(Proposal("burial", {"type": "unforbid_dead", "max": 20},
                                      f"{why['forbidden']} of the fort's {d['unburied']} unburied dead are forbidden "
                                      f"where they lie and {d['free_tombs']} tomb(s) stand free: unforbid them so "
                                      "they are buried", 3))
        if why.get("unreachable"):
            notes.append(f"{why['unreachable']} of the unburied dead lie where the dwarves can't walk"
                         + (f" ({why.get('outside')} outside)" if why.get("outside") else ""))
    if d.get("unburied") and not d.get("free_tombs"):
        ask_player(notes, f"{d['unburied']} citizen bodies wait for burial and there is no free tomb")
    if d.get("loose_coffins") and not d.get("free_tombs"):
        ask_player(notes, f"{d['loose_coffins']} coffins aren't in a tomb zone, so nobody is buried in them")


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
        ask_player(notes, "nobody holds these offices: " + ", ".join(vacant)
                   + " (appoint someone in the nobles screen; "
                   + ("the AI appoints only the manager, bookkeeper, broker, chief medical dwarf, sheriff and captain of the guard)"
                      if appoint else "the AI's appointing is switched off in the Rules tab)"))
    if so.get("starving") or so.get("parched"):
        who = ", ".join(_l(so.get("hungry_names"))[:3])
        ask_player(notes, f"{so.get('starving', 0)} dwarves are starving and {so.get('parched', 0)} parched"
                   + (f" ({who})" if who else "") + ": check they can reach food, drink and water")
    if so.get("grazers_unpastured") and not player_rules(s)["pasture_animals"]:
        ask_player(notes, f"{so['grazers_unpastured']} grazing animals have no pasture and will starve: "
                   "assign them to a pasture zone (the AI's pasture switch is off in the Rules tab)")
