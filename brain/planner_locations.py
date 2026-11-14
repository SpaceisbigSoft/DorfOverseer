"""planner_locations: the fort's locations and what is asked of them (split
out of planner_society in 0.105.25, 13c): temple and guildhall petitions
weighed by the fort's leanings, the meetings' notes, grandeur and a
location's value, the supplies a tavern, temple or library keeps, quick
locations for a need. planner_society re-exports every name here."""

from __future__ import annotations

import re
from digest import _d, _l
from planner_core import *  # noqa: F401,F403

__all__ = ["_location_supply_rules", "_wish_words", "_wish_met", "petition_lean", "wish_key", "_location_petition_rules", "_meeting_notes", "_grandeur_rule", "_location_value_rule", "_quick_location_rule"]


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


def _wish_words(w: dict) -> str:
    tier = int(w.get("tier") or 1)
    if w.get("loc") == "GUILDHALL":
        what = ("a grand guildhall" if tier >= 2 else "a guildhall") + " for the " + \
            str(w.get("profession") or "?").lower().replace("_", " ") + "s"
    else:
        what = ("a temple complex" if tier >= 2 else "a temple") + " to " + str(w.get("deity") or "their god")
    return what


def _wish_met(s: dict, w: dict) -> dict | None:
    """The fort's location that answers a petition's wish, if it has one
    (0.104.163: the highest tier of them, then the most valuable: Teacheroar
    has four miners' guildhalls, the first in the list not the best)."""
    best = None
    for e in _l(_d(s.get("locations")).get("list")):
        if not isinstance(e, dict):
            continue
        if ((w.get("loc") == "GUILDHALL" and e.get("type") == "GUILDHALL"
             and e.get("profession") == w.get("profession"))
                or (w.get("loc") == "TEMPLE" and e.get("type") == "TEMPLE" and (
                    (w.get("religion") is not None and e.get("religion") == w.get("religion"))
                    or (w.get("deity_hf") is not None and e.get("deity_hf") == w.get("deity_hf"))))):
            key = (int(e.get("tier") or 0), int(e.get("value") or 0))
            if best is None or key > (int(best.get("tier") or 0), int(best.get("value") or 0)):
                best = e
    return best


def petition_lean(w: dict, traits: dict) -> tuple[float, str]:
    """(0.104.161, 14.1) How much the fort holds with what a location petition
    asks for, from its sliders, and why in words. A temple: Piety, a little
    Welfare. A guildhall: Craft and Industry, half Trade, a little Welfare,
    less a martial fort's half its Militarism past +50 (its stone goes to the
    army). At petition_decline_lean or lower the petition is declined."""
    t = lambda k: float(traits.get(k, 0) or 0)                    # noqa: E731
    if w.get("loc") == "TEMPLE":
        parts = {"piety": t("piety"), "welfare": t("welfare") / 4}
    else:
        parts = {"craftsmanship": t("craftsmanship"), "industriousness": t("industriousness"),
                 "trade": t("trade") / 2, "welfare": t("welfare") / 4,
                 "militarism": -max(0.0, t("militarism") - 50) / 2}
    lean = sum(parts.values())
    names = {"piety": "Piety", "welfare": "Welfare", "craftsmanship": "Craft", "industriousness": "Industry",
             "trade": "Trade", "militarism": "Militarism"}
    words = ", ".join(f"{names[k]} {int(t(k)):+d}" for k, v in sorted(parts.items(), key=lambda kv: kv[1]) if round(v))
    return lean, (f"the fort's leaning for it is {lean:+.0f}" + (f": {words}" if words else ""))


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
    # petition temples too: those are not answered (the player's switch); guildhalls go on
    no_temples = (not _d(rules_.get("levels")).get("temple", True)) or rules_.get("fort_goal") == "maintain"
    if no_temples and any(w.get("loc") == "TEMPLE" for w in pending + agreed):
        # (0.105.35) the player's own goal or switch: said, not handed back
        notes.append("temple petitions aren't answered or built while " + ("the fort's goal is Maintain"
                                                                          if rules_.get("fort_goal") == "maintain"
                                                                          else "the Temple level is off on the "
                                                                               "Rules tab")
                     + " (DF lets them lapse)")
        pending = [w for w in pending if w.get("loc") != "TEMPLE"]
        agreed = [w for w in agreed if w.get("loc") != "TEMPLE"]
    # agreed: build what isn't there yet. (0.104.163) A hall of the wish's
    # tier answers it: DF settles a location agreement once, when its year runs
    # out (DF wiki, Guildhall: "satisfied and abandoned at once" when work goes
    # on at that moment), not when the hall is finished, so `agreed` keeps it
    # until then. 0.104.160 read that as "unmet" and built a new hall every
    # few minutes (Teacheroar, 1 Nov 14:29-14:51: miners' guildhalls 17, 18,
    # 19 and project 233 beside the old one, the petition still open; the
    # retarget then turned each hall miners -> Teshkad -> miners, 10 times).
    def met(w):
        e = _wish_met(s, w)
        return e is not None and int(e.get("tier") or 0) >= int(w.get("tier") or 1)

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
            # (0.104.163) nothing to give it to, and no location petition
            # waits that might be: a hall the fort has already is not dug
            # again (cancelled while under a quarter is dug)
            dig = _d(p.get("dig"))
            total, dug = int(dig.get("total") or 0), int(dig.get("dug") or 0)
            if not pending and total and dug * 4 < total and p.get("id") is not None:
                proposals.append(Proposal("petition_retarget", {"type": "cancel_project", "project_id": p["id"]},
                                          f"the hall being dug was for {_wish_words(own)}, which the fort has "
                                          f"already ({dug} of {total} tiles dug): not dug again", 5))
                return
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
        if e and met(w):
            notes.append(f"{_wish_words(w)} (agreed {w.get('days')} days ago) stands at tier {e.get('tier')}: "
                         f"DF settles the agreement when its year is out (in about "
                         f"{max(0, 336 - int(w.get('days') or 0))} days)")
        elif e and int(e.get("tier") or 0) < int(w.get("tier") or 1):
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
        # (0.104.161, 14.1) a fort that doesn't hold with it says no: War-hold
        # and Monastery agreed ~100 petitions each, none declined. Declining
        # makes no promise (an agreed hall left unbuilt upsets the petitioners);
        # prayer is still met by the temple-to-all-gods rule (prayer_uncovered).
        lean, why = petition_lean(w, traits)
        if lean <= cfg["petition_decline_lean"]:
            proposals.append(Proposal("petition_answer", {"type": "answer_petition", "id": w.get("id"),
                                                          "accept": False, "wish": wish_key(w)},
                                      f"a petition asks for {_wish_words(w)}: decline ({why})", 6))
            return
        if tier >= 2 and not (traits.get("grandeur", 0) > 0 or (w.get("loc") == "TEMPLE" and traits.get("piety", 0) > 0)):
            # (0.105.35) nothing waits for the player: the AI declines it (was
            # "left to you"); declining makes no promise to keep
            proposals.append(Proposal("petition_answer", {"type": "answer_petition", "id": w.get("id"),
                                                          "accept": False, "wish": wish_key(w)},
                                      f"a petition asks for {_wish_words(w)}: decline (a fort that doesn't care "
                                      "for grandeur agrees to temples and guildhalls, not their grand tier)", 6))
            return
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
        # (0.105.0) the AI answers it once shown the screen's buttons (brain/planner_world.py)
        # (0.105.35) nothing waits for the player: when it knows the buttons
        # the AI answers (a note); else the Needs you says what it does meanwhile
        wm = _d(_d(s.get("world")).get("meeting"))
        known = set(str(b) for b in _l(wm.get("buttons")))
        need = {"Done"} if wm.get("requests") else {"Yes", "No"}
        if wm.get("open") and not wm.get("land_holder") and need <= known:
            notes.append(f"DF's meeting screen is open ({who}): the AI answers it")
            return
        if wm.get("open") and wm.get("land_holder"):
            # (0.105.35 merge) the barony's own Needs you is planner_world's; here only said
            notes.append(f"DF's meeting screen is open ({who}) and asks for a barony's holder, which the AI "
                         "can't pick: it leaves the screen after 2 minutes so the game goes on")
            return
        ask_player(notes, f"DF's meeting screen is open ({who}) and the AI can't press its buttons yet (it hasn't "
                          "been shown where they are; with one open, the mouse on Yes: python brain\\probe_meeting.py "
                          "--here Yes; then No, and Done on the requests screen); meanwhile it leaves the screen "
                          "after 2 minutes (the meeting ends without an agreement) so the game goes on")
    elif int(m.get("popups") or 0) > 0:
        # (0.94.1) a queued meeting popup doesn't hold the game (region2 ran
        # on through days of them): a note, not a Needs you
        # (0.105.24) 2-5 Nov, six forts: 295 such notes, the screen never
        # opened, each popup gone on its own in 5-28 real minutes. DFHack has
        # no safe way to show or drop one (taking it off DF's list could
        # leave the noble's meeting half done), so it stays a note.
        notes.append(f"a meeting waits to be shown in DF ({who}); the game runs on meanwhile")
    elif acts:
        notes.append("meetings under way: " + "; ".join(
            f"{a.get('actor')} with {a.get('noble')}" + (f" (tree quota {a['tree_quota']})" if a.get("tree_quota") else "")
            for a in acts[:3]))


def _zone_full(s: dict, memory, zone_id) -> int | None:
    """(item7) Days the zone stays booked full (no free floor), or None."""
    if memory is None or not isinstance(_d(s.get("date")).get("tick"), int):
        return None
    return zone_full_days(memory, zone_id, abs_tick(s))


def _grandeur_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
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
    # (item7) a hall whose zone has no free floor waits (another is dressed meanwhile)
    roomy = [e for e in halls if _zone_full(s, memory, _l(e["zones"])[0]) is None]
    if not roomy:
        e = min(halls, key=lambda e: int(e.get("value") or 0))
        notes.append(f"a grand fort (Grandeur {int(g):+d}): the halls under {want} have no free floor for "
                     f"another statue (zone {_l(e['zones'])[0]} looked at again in "
                     f"{_zone_full(s, memory, _l(e['zones'])[0])} day(s)); engraving adds the most now")
        return
    e = min(roomy, key=lambda e: int(e.get("value") or 0))
    what = str(e.get("type")).lower().replace("inn_", "").replace("_", " ")
    if int(_d(s.get("supplies")).get("statues") or 0) > 0:
        proposals.append(Proposal("grandeur", {"type": "place_in_zone", "zone_id": _l(e["zones"])[0], "what": "statue"},
                                  f"a grand fort (Grandeur {int(g):+d}): the {what} is worth {e.get('value') or 0} of "
                                  f"the {want} it should be: put a statue in it", 6))
    elif not queued(s, {"stone_statue"}) and not stone_short(s, 10):
        proposals.append(Proposal("grandeur", {"type": "work_order", "recipe": "stone_statue", "amount": 3},
                                  f"a grand fort (Grandeur {int(g):+d}): the {what} is worth {e.get('value') or 0} of "
                                  f"the {want} it should be: make statues for it", 6, True))


def _location_value_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
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
        full = _zone_full(s, memory, _l(e["zones"])[0])
        if full is not None:
            notes.append(f"{_wish_words(w)} is worth {value} of the {need} it needs, and its zone has no free "
                         f"floor for another statue (looked at again in {full} day(s))")
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
