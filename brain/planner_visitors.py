"""planner_visitors: visitors, petitions and the fort's doors to outsiders
(split out of planner_society in 0.105.25, 13c): petitions answered by
Outsiders (performers, scholars, hunters, residency, citizenship notes);
artifact heists and the lockout after one; the mayor swamped by visitors;
the tavern, temples, library and guildhalls shut to visitors (or opened
again). planner_society re-exports every name here."""

from __future__ import annotations

from digest import _d, _l
from planner_core import *  # noqa: F401,F403

__all__ = ["PETITION_KINDS", "petition_orders_wanted", "_petition_rules", "_citizenship_notes", "residency_stance", "_residency_rule", "CLOSABLE_LOCATIONS", "HEISTS_KEEP", "note_heists", "heist_lockout", "heist_lockout_days", "mayor_meetings", "_complaint_holder", "visitor_shut", "location_stale", "note_locations", "LOCATION_WORDS", "_location_words", "_location_access_rule", "outsider_orders"]


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
        _citizenship_notes(s, cfg, pending, notes)
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


def _citizenship_notes(s: dict, cfg: dict, pending: list, notes: list) -> None:
    """(0.105.24, 12b) Citizenship petitions are the player's: DFHack 53.16-r3
    can't reach DF's standing order for them (the self-test's missing
    standing_orders_petition_citizenship), the bridge answers only temple,
    guildhall and residency petitions, and agreeing by the agreement's flag
    left a residency applicant a guest in B (0.105.11), so agreeing to
    citizenship that way isn't known to make a citizen. Said with counts:
    a Needs you when the fort would take them (under its population target,
    not closed, the Rules let visitors stay), else a note. Applicants who
    left or died are counted apart (nothing to agree to)."""
    cit = [e for e in pending if str(e.get("type") or "").lower() == "citizenship"]
    if not cit:
        return
    gone = [e for e in cit if not _d(e.get("applicant")).get("on_map") or _d(e.get("applicant")).get("dead")]
    here = [e for e in cit if e not in gone]
    tail = f" ({len(gone)} more from visitors who left or died)" if gone else ""
    if not here:
        notes.append(f"{len(gone)} citizenship petition(s) from visitors who left or died wait on DF's petitions "
                     "screen (the AI can't answer citizenship)")
        return
    vamp = [e for e in here if e.get("vampire")]
    names = ", ".join(str(e.get("name")) for e in here[:3] if e.get("name"))
    citizens = int(_d(s.get("dwarves")).get("total") or 0)
    target = growth_target(s, cfg)
    wanted = petition_orders_wanted(s, cfg).get("citizenship") == 1 and player_rules(s).get("accept_visitors", True)
    if wanted and len(vamp) < len(here):
        ask_player(notes, f"{len(here) - len(vamp)} citizenship petition(s) wait and the fort would take them "
                          f"({citizens} citizens, the target {target}): agree on DF's petitions screen"
                          + (f" ({names})" if names else "") + tail
                          + "; the AI can't (DFHack can't reach the standing order, and agreeing outside the "
                            "screen isn't known to make a citizen)"
                          + (f"; {len(vamp)} of them a vampire: leave that one" if vamp else ""))
    else:
        why = ("a vampire" if wanted else "this fort isn't taking citizens now (closed, at its population target, "
                                          "or the Rules keep visitors out)")
        notes.append(f"{len(here)} citizenship petition(s) wait{tail}: {why}; decline them on DF's petitions "
                     "screen if you like (the AI can't answer citizenship)")


def residency_stance(traits: dict, cfg: dict) -> str:
    """(0.105.9) Outsiders: "accept" petitions to stay from a welcoming fort
    (30 and up), "decline" from a closed one (-50 and below), else "stale"
    (only the ones whose visitor is gone or dead are cleared)."""
    o = traits.get("outsiders", 0) or 0
    if o >= cfg["residency_accept_outsiders"]:
        return "accept"
    if outsider_orders(traits)["closed"]:          # (review) -50 and below, as DF's standing orders
        return "decline"
    return "stale"


def _residency_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(0.105.9, 14.1) Petitions to stay (Residency) waited by the hundred in
    every fort (300+ each at y257), whatever the Outsiders slider said: DF's
    standing orders that answer them are out of DFHack 53.16-r3's reach.
    Now the AI answers them itself, by Outsiders (residency_stance):
    a closed fort declines them, 25 at a time; every fort clears the ones
    whose visitor has left or died; a welcoming fort agrees, first one as a
    probe: agreeing is taken to work only once that visitor shows as DF's
    resident (the report's petitions.residents) within a few days. If not,
    it agrees to no more, and says so (they wait for you on DF's petitions
    screen). With the Rules switch "accept visitors" off, none is agreed."""
    pt = _d(s.get("petitions"))
    if "error" in pt:
        return
    pending = [e for e in _l(pt.get("pending")) if isinstance(e, dict) and e.get("type") == "Residency"
               and isinstance(e.get("id"), int)]
    st = _d(memory.residency)
    memory.residency = st
    now = abs_tick(s)
    residents = pt.get("residents")
    # the probe's verdict (a visitor who left before it could show is no verdict)
    probe = _d(st.get("probe"))
    if probe and st.get("works") is None and isinstance(residents, list):
        if probe.get("unit") in residents:
            st["works"] = True
            st["since"] = now
        elif (isinstance(probe.get("tick"), int)
              and now - probe["tick"] >= cfg["residency_probe_days"] * TICKS_PER_DAY):
            # (review) the visitor may have left in the meantime: a second
            # probe before the verdict
            st["tries"] = int(st.get("tries") or 0) + 1
            if st["tries"] < 2:
                st.pop("probe", None)
                probe = {}
            else:
                st["works"] = False
                st["since"] = now
    if (st.get("works") is False and isinstance(st.get("since"), int)
            and now - st["since"] >= cfg["residency_reprobe_days"] * TICKS_PER_DAY):
        st.clear()                                  # a year on: one more probe
        probe = {}
    if not pending:
        return
    traits = _traits(s) if isinstance(s.get("settings"), dict) else {}
    stance = residency_stance(traits, cfg)
    if stance == "accept" and not player_rules(s).get("accept_visitors", True):
        stance = "stale"
    gone = [e["id"] for e in pending
            if not _d(e.get("applicant")).get("on_map") or _d(e.get("applicant")).get("dead")]
    batch = cfg["residency_batch"]
    if stance == "decline":
        ids = [e["id"] for e in pending][:batch]
        proposals.append(Proposal("residency", {"type": "answer_petition", "ids": ids, "accept": False,
                                                "residency": True},
                                  f"{len(pending)} petition(s) to stay wait, and this fort keeps to itself "
                                  f"(Outsiders {traits.get('outsiders', 0)}): decline {len(ids)}", 6))
        return
    if gone:
        ids = gone[:batch]
        proposals.append(Proposal("residency", {"type": "answer_petition", "ids": ids, "accept": False,
                                                "residency": True},
                                  f"{len(gone)} petition(s) to stay from visitors who have left or died: "
                                  f"clear {len(ids)}", 7))
        return
    if stance != "accept":
        return
    # (review) never a vampire; mercenaries and monster hunters only as the
    # standing orders would take them (Militarism)
    fighters = petition_orders_wanted(s, cfg)
    def welcome(e):
        if e.get("vampire") or _d(e.get("applicant")).get("unit") is None:
            return False
        r = str(e.get("reason") or "").lower()
        if "mercenar" in r or "merc" == r:
            return bool(fighters.get("mercenary"))
        if "monster" in r or "hunt" in r:
            return bool(fighters.get("monster_hunter"))
        return True
    here = [e for e in pending if welcome(e)]
    if not here:
        return
    works = st.get("works")
    if not cfg["residency_accept_by_flag"]:
        # (0.105.11) B, 2 Nov: Mistêm Zonåm's petition agreed by the flag, and DF
        # kept her a guest (the player looked: Other, "Guest / Listen to Story")
        ask_player(notes, f"{len(here)} petition(s) to stay from visitors this welcoming fort would take: agree to "
                          "them on DF's petitions screen (the AI can only decline; agreeing from outside the "
                          "screen leaves the visitor a guest)")
        return
    if works is False:
        ask_player(notes, f"the AI agreed to a petition to stay and DF didn't make the visitor a resident: "
                          f"{len(pending)} petition(s) to stay wait for you on DF's petitions screen")
        return
    if works is None and not probe:
        e = here[0]
        proposals.append(Proposal("residency", {"type": "answer_petition", "id": e["id"], "accept": True,
                                                "residency": True},
                                  f"a welcoming fort (Outsiders {traits.get('outsiders', 0)}): agree to "
                                  f"{e.get('name') or 'a visitor'}'s petition to stay (the first: the AI watches "
                                  "that DF makes them a resident)", 6))
        return
    if works is None:
        return                                  # waiting on the probe
    ids = [e["id"] for e in here][:batch]
    proposals.append(Proposal("residency", {"type": "answer_petition", "ids": ids, "accept": True,
                                            "residency": True},
                              f"a welcoming fort (Outsiders {traits.get('outsiders', 0)}): agree to "
                              f"{len(ids)} petition(s) to stay", 6))


CLOSABLE_LOCATIONS = ("INN_TAVERN", "TEMPLE", "LIBRARY", "GUILDHALL")


HEISTS_KEEP = 20            # (0.105.24) heists remembered (each [tick, who])


def note_heists(state: dict, memory, events: list) -> int:
    """(0.105.24) Artifact heists and visitors' killings, from the bridge's
    events, one a thief a day. A heist is DF's "X was spotted sneaking
    around! "You will not stand between me and <artifact>!"" (a snatcher or a
    raider fleeing says other words). A citizen killed by a visitor counts
    too, unless the citizen was berserk (C, E, F, 2 Nov: three failed moods
    went berserk and the bards and poets fought back) or the killer died
    first (an old wound, not a visitor about now). 2-5 Nov forensics: 34
    citizens killed by outsiders; 24 by artifact thieves, most of whom had
    come in as visitors (19 of 23 asked the mayor for a meeting first)."""
    now = abs_tick(state)
    day = now // TICKS_PER_DAY
    have = {(int(t[0]) // TICKS_PER_DAY, str(t[1])) for t in memory.heists
            if isinstance(t, list) and len(t) == 2 and isinstance(t[0], int)}
    n = 0
    for e in events or []:
        if not isinstance(e, dict):
            continue
        who = None
        if e.get("kind") == "report":
            text = " ".join(str(e.get("text") or "").split())
            if "sneaking around" in text and "stand between me and" in text:
                who = text.split(" was spotted")[0].replace("The ", "", 1)[:40]
        elif (e.get("kind") == "death" and e.get("own_civ") and not e.get("animal") and not e.get("again")
                and e.get("killer_visitor") and not e.get("killer_dead")
                and str(e.get("mood") or "").lower() != "berserk"):
            who = str(e.get("killer") or "a visitor").split(",")[0][:40]
        if not who or (day, who) in have:
            continue
        have.add((day, who))
        memory.heists.append([now, who])
        n += 1
    memory.heists = [t for t in memory.heists if isinstance(t, list) and len(t) == 2][-HEISTS_KEEP:]
    return n


def heist_lockout_days(s: dict, cfg: dict) -> int:
    """(0.105.26) How long a heist shuts the locations to visitors:
    `heist_lockout_days` (168), but `heist_lockout_days_welcoming` (28) in a
    fort whose point is visitors (Outsiders `visitor_shut_welcoming`, 100, or
    more: the Merchant city, shut half a year a heist before). 0: never."""
    days = int(cfg.get("heist_lockout_days") or 0)
    traits = _traits(s) if isinstance(s.get("settings"), dict) else {}
    if days > 0 and int(traits.get("outsiders", 0) or 0) >= int(cfg.get("visitor_shut_welcoming") or 100):
        days = min(days, int(cfg.get("heist_lockout_days_welcoming", 28) or 0))
    return days


def heist_lockout(s: dict, memory, cfg: dict):
    """(0.105.24) The last heist still inside the lockout ([tick, who]), or None.
    (0.105.24) None too while the Rules switch heist_lockout is off.
    (0.105.26) The lockout's length: heist_lockout_days (shorter in a welcoming fort)."""
    days = heist_lockout_days(s, cfg)
    if days <= 0:
        return None
    if isinstance(s.get("settings"), dict) and not player_rules(s)["heist_lockout"]:
        return None
    now = abs_tick(s)
    recent = [t for t in _l(getattr(memory, "heists", None)) if isinstance(t, list) and len(t) == 2
              and isinstance(t[0], int) and 0 <= now - t[0] < days * TICKS_PER_DAY]
    return max(recent, key=lambda t: t[0]) if recent else None


def mayor_meetings(s: dict, first: str = "") -> tuple:
    """(0.105.24) The meetings of the noble who hears complaints (`first`: the
    start of their name, "" for any noble): (under way, waiting, with visitors)."""
    m = _d(s.get("meetings"))
    acts = [a for a in _l(m.get("activities")) if isinstance(a, dict)
            and (not first or first in str(a.get("noble") or ""))]
    waiting = int(m.get("requests") or 0)
    # (0.105.26) residents (living here, not citizens) aren't visitors come to ask
    vis = (max(0, int(m.get("requests_visitors") or 0) - int(m.get("requests_residents") or 0))
           + sum(1 for a in acts if a.get("visitor") and not a.get("resident")))
    return acts, waiting, vis


def _complaint_holder(s: dict):
    """(0.105.24) The mayor (or expedition leader): (office code, [names]), or None."""
    offices = _d(_d(s.get("offices")).get("offices"))
    return next(((code, _l(_d(offices.get(code)).get("held"))) for code in ("MAYOR", "EXPEDITION_LEADER")
                 if _l(_d(offices.get(code)).get("held"))), None)


def visitor_shut(s: dict, memory, cfg: dict):
    """(0.105.24) The mayor's rest from visitors, or None. It starts when the
    mayor's meetings (under way and waiting) are mostly with visitors
    (`visitor_shut_share`, at least `visitor_shut_meetings_min`) while
    `visitor_shut_unheard_min` citizens went unable to complain lately; it
    lasts `visitor_shut_days`, then the locations open and it is looked at
    afresh. Never with the Rules switch shut_to_visitors off, nor in a fort
    whose point is visitors (Outsiders `visitor_shut_welcoming` or more: the
    Merchant city).
    (0.105.26) Changes no memory (plan() never does): the rest under way is a
    copy of memory.visitor_shut; a new one comes back with "new": True, and
    the rule carries it on its location_access action, which record() keeps
    only when the shut went through (a shut held back by a cooldown, the
    action limit or the halt starts no clock). After the AI reopened (memory
    {"reopened", "unheard_at"}) it shuts again only for complaints made
    since: "unable to complain" lingers in the census (its 28 days), so the
    count at the reopen alone shut it again right away. Residents meeting
    the mayor aren't visitors (mayor_meetings)."""
    w = memory.visitor_shut if isinstance(getattr(memory, "visitor_shut", None), dict) else {}
    traits = _traits(s) if isinstance(s.get("settings"), dict) else {}
    if isinstance(s.get("settings"), dict) and not player_rules(s)["shut_to_visitors"]:
        return None
    if int(traits.get("outsiders", 0) or 0) >= cfg["visitor_shut_welcoming"]:
        return None
    now = abs_tick(s)
    until = w.get("until")
    if isinstance(until, int) and int(w.get("tick") or 0) <= now:
        if now < until:
            return dict(w)
        return None             # over: the locations open first (record or note_locations then forget it)
    from planner_society import _cause_citizens     # (13c) the stress census lives there
    unheard = _cause_citizens(s, "UnableComplain")
    if unheard < cfg["visitor_shut_unheard_min"]:
        return None
    back = w.get("reopened")
    if isinstance(back, int) and 0 <= now - back:
        census = int(_d(_d(s.get("needs")).get("stress_causes")).get("days") or 28)
        # the census still holds thoughts from before the reopen: only those
        # past the count then are surely new (each citizen counted once)
        if now - back < census * TICKS_PER_DAY and unheard - int(w.get("unheard_at") or 0) < cfg["visitor_shut_unheard_min"]:
            return None
    holder = _complaint_holder(s)
    name = str(holder[1][0]) if holder else ""
    acts, waiting, vis = mayor_meetings(s, name.split(" ")[0] if name else "")
    total = len(acts) + waiting
    if vis < cfg["visitor_shut_meetings_min"] or total <= 0 or vis < cfg["visitor_shut_share"] * total:
        return None
    return {"tick": now, "until": now + int(cfg["visitor_shut_days"]) * TICKS_PER_DAY,
            "visitors": vis, "meetings": total, "unheard": unheard, "new": True}


def location_stale(s: dict, memory, cfg: dict, loc_id: int) -> bool:
    """(0.105.26) A location the AI shut that reads open: is the report older
    than the shut? The locations section is cached (2 days), and before
    0.105.26 a shut didn't clear it, so the next cycles read the old "open",
    took it for the player's doing and never reopened it (locations_yours).
    Stale when the section was built (its `built` tick) no later than the
    AI's last action on it; from an older bridge (no `built`), when it reads
    open within `location_stale_days` of that action."""
    t = _d(getattr(memory, "locations_acted", None)).get(str(loc_id))
    if not isinstance(t, int):
        return False
    built = _d(s.get("locations")).get("built")
    if isinstance(built, int):
        return built <= t
    return abs_tick(s) - t < int(cfg.get("location_stale_days", 4)) * TICKS_PER_DAY


def note_locations(s: dict, memory, cfg: dict) -> None:
    """(0.105.26) The locations' bookkeeping, from a fresh report before
    planning (moved out of plan(), which never changes memory): one the AI
    shut that you opened again (in a report built since the shut) is yours,
    forgotten and never shut again; the mayor's rest over with nothing of the
    AI's left shut (you opened them, or they opened already) is forgotten,
    leaving the reopen's mark for the complaints counted then."""
    locs = [e for e in _l(_d(s.get("locations")).get("list"))
            if isinstance(e, dict) and isinstance(e.get("id"), int) and isinstance(e.get("flags"), list)]
    if not locs:
        return
    mine = [i for i in (memory.locations_closed or []) if isinstance(i, int)]
    yours = {e["id"] for e in locs if e["id"] in mine and "VISITORS_ALLOWED" in e["flags"]
             and not location_stale(s, memory, cfg, e["id"])}
    if yours:
        memory.locations_closed = [i for i in mine if i not in yours]
        memory.locations_yours = sorted(set(memory.locations_yours or []) | yours)
        mine = memory.locations_closed
    w = memory.visitor_shut if isinstance(getattr(memory, "visitor_shut", None), dict) else {}
    now = abs_tick(s)
    if isinstance(w.get("until"), int) and now >= w["until"]:
        held = [e["id"] for e in locs if e["id"] in mine and "VISITORS_ALLOWED" not in e["flags"]]
        if not held:
            from planner_society import _cause_citizens
            memory.visitor_shut = {"reopened": now, "unheard_at": _cause_citizens(s, "UnableComplain")}
    acted = _d(getattr(memory, "locations_acted", None))
    stale = int(cfg.get("location_stale_days", 4)) * TICKS_PER_DAY
    memory.locations_acted = {k: t for k, t in acted.items() if isinstance(t, int) and 0 <= now - t < max(stale, TICKS_PER_YEAR)}


LOCATION_WORDS = {"INN_TAVERN": "tavern", "TEMPLE": "temple", "LIBRARY": "library", "GUILDHALL": "guildhall"}


def _location_words(locs: list, ids) -> str:
    """(0.105.24) "the tavern, 2 temples and the library", in plain words."""
    n = {}
    for e in locs:
        if e["id"] in ids and e.get("type") in LOCATION_WORDS:
            n[e["type"]] = n.get(e["type"], 0) + 1
    parts = [(f"the {LOCATION_WORDS[k]}" if c == 1 else f"{c} {LOCATION_WORDS[k]}s")
             for k, c in sorted(n.items(), key=lambda kv: CLOSABLE_LOCATIONS.index(kv[0]))]
    return (", ".join(parts[:-1]) + " and " + parts[-1]) if len(parts) > 1 else (parts[0] if parts else "")


def _location_access_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(0.105.12, 14.1 step 4) A closed fort (Outsiders -50 or lower: the
    Hermit hold, the War-hold) keeps its tavern, temples, library and
    guildhalls to its own: visitors not allowed (DF's location screen;
    residents still welcome; a hospital always open). A fort that opens up
    again gets back the ones the AI shut. Why: at y257 the Hermit hold had the
    most visitors of the six (92), Outsiders -150 showing nothing.
    (0.105.24) Any fort does the same for `heist_lockout_days` after an
    artifact heist or a visitor's killing (note_heists): the 2-5 Nov thieves
    were visitors first; D, shut at 23:06 2 Nov, had 8 heists before and none
    after, and A's later thieves all came from the map's edge, where the
    gate and the squad meet them. Then the ones the AI shut open again.
    (0.105.24) The lockout has its Rules switch (heist_lockout; off, a
    lockout under way is lifted); and the same locations shut for
    `visitor_shut_days` when the mayor is swamped by visitors (visitor_shut,
    its switch shut_to_visitors). Shut while either holds, the longer
    winning; one the player shut is never the AI's to open."""
    locs = [e for e in _l(_d(s.get("locations")).get("list"))
            if isinstance(e, dict) and isinstance(e.get("id"), int) and isinstance(e.get("flags"), list)]
    if not locs:
        return
    traits = _traits(s) if isinstance(s.get("settings"), dict) else {}
    closed = outsider_orders(traits)["closed"]
    lock = None if closed else heist_lockout(s, memory, cfg)
    was = dict(memory.visitor_shut) if isinstance(getattr(memory, "visitor_shut", None), dict) else {}
    was = was if isinstance(was.get("until"), int) else {}
    swamp = None if closed else visitor_shut(s, memory, cfg)
    now = abs_tick(s)
    mine = [i for i in (memory.locations_closed or []) if isinstance(i, int)]
    # (0.105.26) plan() changes no memory: one the AI shut and you opened again
    # (in a report built since) is yours, left alone here and forgotten by
    # note_locations; one that reads open in a report older than the AI's own
    # shut is that old report: neither yours nor shut again
    stale = {i for i in mine if location_stale(s, memory, cfg, i)}
    yours = {e["id"] for e in locs if e["id"] in mine and "VISITORS_ALLOWED" in e["flags"] and e["id"] not in stale}
    if closed or lock or swamp:
        # (review) one the AI shut and you opened again is yours: forgotten, never shut again
        left_open = set(memory.locations_yours or []) | yours
        shut = [e["id"] for e in locs if e.get("type") in CLOSABLE_LOCATIONS and "VISITORS_ALLOWED" in e["flags"]
                and e["id"] not in left_open and e["id"] not in stale]
        lock_left = (heist_lockout_days(s, cfg) - (now - lock[0]) // TICKS_PER_DAY) if lock else 0
        swamp_left = -(-(int(swamp["until"]) - now) // TICKS_PER_DAY) if swamp else 0
        # (0.105.24) the mayor's rest said while it lasts, with what is shut
        # (0.105.26) a new one only with something to shut (it starts when the shut goes through)
        held = [i for i in mine if i not in yours]
        if swamp and not closed and swamp_left >= lock_left and (shut or (held and not swamp.get("new"))):
            notes.append(f"visitors kept out of {_location_words(locs, set(shut) | set(held)) or 'the locations'} "
                         f"for {max(1, swamp_left)} more day(s) (residents still welcome): {swamp.get('visitors')} "
                         f"of the mayor's {swamp.get('meetings')} meetings were with visitors (performers and "
                         f"scholars asking to stay) and {swamp.get('unheard')} citizens couldn't lodge a complaint; "
                         "the Rules switch \"Shut to visitors when mayor swamped\" turns this off")
        if shut:
            if closed:
                why = f"this fort keeps to itself (Outsiders {traits.get('outsiders', 0)})"
            elif lock and lock_left >= swamp_left:
                why = (f"a thief or a violent visitor ({lock[1]}) struck: visitors kept out "
                       f"for {max(1, lock_left)} more day(s) (thieves came as guests)")
            else:
                why = (f"the mayor is swamped by visitors ({swamp.get('visitors')} of {swamp.get('meetings')} "
                       f"meetings; {swamp.get('unheard')} citizens couldn't lodge a complaint): visitors kept "
                       f"out for {max(1, swamp_left)} day(s) so the citizens are heard")
            action = {"type": "location_access", "ids": shut, "visitors": False}
            if swamp and swamp.get("new") and not closed:
                # (0.105.26) the mayor's rest, kept by record() when the shut goes through
                action["visitor_shut"] = {k: v for k, v in swamp.items() if k != "new"}
            proposals.append(Proposal("location_access", action,
                                      f"{why}: {_location_words(locs, set(shut))} ({len(shut)} location(s)) "
                                      "closed to visitors (residents still welcome)",
                                      3 if lock else 5 if swamp and not closed else 6))
        return
    reopen = [e["id"] for e in locs if e["id"] in mine and "VISITORS_ALLOWED" not in e["flags"]]
    if not reopen:
        return                                    # (0.105.26) nothing held: note_locations forgets the mayor's rest
    rules_ = player_rules(s) if isinstance(s.get("settings"), dict) else {}
    why = [f"Outsiders {traits.get('outsiders', 0)}"]
    if _l(getattr(memory, "heists", None)):
        why.append("the lockout after a theft is off on the Rules tab" if rules_.get("heist_lockout") is False
                   else f"no heist for {heist_lockout_days(s, cfg)} days")
    if was:
        why.append("shutting out visitors for the mayor is off on the Rules tab"
                   if rules_.get("shut_to_visitors") is False
                   else f"the mayor's {int(cfg['visitor_shut_days'])} days without visitors are over")
    from planner_society import _cause_citizens
    # (0.105.26) the reopen's mark (the complaints counted now), kept by
    # record() when it goes through: the mayor's rest starts again only for
    # complaints made since
    action = {"type": "location_access", "ids": reopen, "visitors": True,
              "visitor_shut": {"reopened": now, "unheard_at": _cause_citizens(s, "UnableComplain")}}
    proposals.append(Proposal("location_access", action,
                              f"the fort opens up again ({'; '.join(why)}): "
                              f"{len(reopen)} location(s) the AI closed let visitors in again", 6))


def outsider_orders(traits: dict) -> dict:
    """Outsiders (closed - welcoming): which petitions to stay DF's standing
    orders may accept: performers, scholars and those seeking sanctuary
    from -30; monster hunters, mercenaries and new citizens never at -50 or
    lower (whatever Militarism and Growth say)."""
    o = traits.get("outsiders", 0) or 0
    guests = 1 if o >= -30 else 0
    closed = o <= -50
    return {"guests": guests, "closed": closed}
