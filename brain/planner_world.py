"""(0.105.0, phases 12b and 13b) The world outside the fort.

The `world` report (lua/ai-diplomacy.lua) says which civilisations the fort
knows, at war or peace, who has besieged it, the tribute asked or offered,
the caravans' trade agreements (what they'd pay more for), and the meeting
screen when it is open. From it:

  * a meeting with a diplomat or the liaison is answered with the AI's
    defaults (agree to trade, to the elves' tree quota; peace and tribute by
    the Rules choices (0.105.41: peace in brain/planner_peace.py); the requests' wishes ticked), through buttons the
    player showed the AI once; until then it stays a Needs-you;
  * a caravan from a civilisation at war is not traded with (the goods stay
    home, the broker isn't called);
  * goods a caravan's agreement asks for at a good price are made for the
    next one (a work order while hands are idle);
  * the civilisations that besieged the fort are kept (a grudge list) and
    feed the Grudge-keepers quirk;
  * a messenger is appointed when the fort has the post, and a site not in
    contact is named for "Make contact" (13b) once one is free: the World
    screen's last steps (the messenger, the confirm) have never been seen, so
    the AI says what to send and watches the mission in the `missions` report;
    (0.105.24) with the Rules switch send_messenger on, it drives the World
    screen itself as far as the recorded steps go (lua/ai-mission-send.lua).

Citizenship petitions (r10 p1): agreed by DF's own standing order, which the
bridge reaches on Windows by DF's symbol names (planner_visitors
_petition_rules; docs/dfhack-notes.md, "Petitions (r10)"); declined like
petitions to stay when the fort won't take them; never agreed by the
agreement's flag (not known to make the visitor a citizen).
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (PLANNER_CONFIG, Proposal, TICKS_PER_DAY, TICKS_PER_YEAR, abs_tick, ask_player,
                          player_rules, queued, reachable_threats, young_fort, _traits)

__all__ = ["_meeting_answer_rule", "_world_notes", "_hostile_trade_filter", "_export_rule", "_messenger_rule",
           "_contact_rule", "grudge_facts", "note_grudges", "note_world", "export_wishes", "EXPORT_RECIPES",
           "TRADE_ACTIONS", "meeting_wishes", "WISH_CATEGORIES", "note_contact_sent"]

HOSTILE = ("TotalWar", "Skirmishing")
# the bridge's trade actions: none while only a hostile civ's caravan is here
TRADE_ACTIONS = ("bring_goods", "call_trader", "open_trade", "trade_deal")
# DF item types a trade agreement names -> the fort's recipe that makes one
EXPORT_RECIPES = {
    "CRAFTS": "stone_crafts", "FIGURINE": "stone_crafts", "TOTEM": "bone_crafts", "SCEPTER": "stone_crafts",
    "CROWN": "stone_crafts", "RING": "stone_ring", "EARRING": "stone_earring", "AMULET": "stone_amulet",
    "BRACELET": "stone_bracelet", "GOBLET": "stone_mugs", "BLOCKS": "stone_blocks", "TABLE": "stone_table",
    "CHAIR": "stone_chair", "DOOR": "stone_door", "CABINET": "stone_cabinet", "BOX": "stone_chest",
    "COFFIN": "stone_coffin", "STATUE": "stone_statue", "SLAB": "stone_slab", "BARREL": "wooden_barrel",
    "BIN": "wooden_bin", "BUCKET": "wooden_bucket", "CAGE": "wooden_cage", "SPLINT": "wooden_splint",
    "CRUTCH": "wooden_crutch", "CLOTH": "weave_plant_cloth",
}
# the fort's trade wants (planner_industry trade_wants keys) -> DF's request
# categories on the liaison's Requests screen (entity_sell_category)
WISH_CATEGORIES = {"FOOD": ("Meat", "Cheese"), "DRINK": ("Drinks",), "BAR:STEEL": ("MetalBars",),
                   "BAR:IRON": ("MetalBars",), "BAR:COAL": ("MetalBars",), "CLOTH": ("ClothPlant",),
                   "SKIN_TANNED": ("Leather",), "THREAD": ("ThreadPlant",), "WOOD": ("Wood",), "SOAP": ("Extracts",),
                   "TALLOW": ("Extracts",)}
EXPORT_MIN_PCT = 110            # a price this far over the usual (128 = 100%) is worth making for
EXPORT_AMOUNT = 5
EXPORT_MEMORY_DAYS = 336        # a caravan's wish kept a year, for the next caravan


def _world(s: dict) -> dict:
    return _d(s.get("world"))


def _seen(memory) -> dict:
    """The world's memory (memory.world_seen): grudges, export wishes, the
    last contact named. Read only (note_world writes it, before planning)."""
    ws = getattr(memory, "world_seen", None) if memory is not None else None
    return _d(ws)


def note_world(s: dict, memory) -> None:
    """Bookkeeping before planning (planner.note_cycle): the grudge list, the
    caravans' export wishes, and when a contact was last named."""
    if memory is None:
        return
    if not isinstance(getattr(memory, "world_seen", None), dict):
        memory.world_seen = {}
    note_grudges(s, memory)
    from planner_contact import note_contacts      # (r10 p3) the contact book: per site sent, made, failed
    note_contacts(s, memory)
    from planner_peace import note_attacks          # (0.105.41, item 8) the civs the fort attacked
    note_attacks(s, memory)
    memory.world_seen["export"] = export_wishes(s, memory)
    # (0.105.48, K9) stamped here only when the rule merely names the site (the
    # AI doesn't send it: the switch off, or the World button never shown);
    # a send is stamped in note_contact_sent once the bridge took it (the
    # audit: a gate opened first, or "not now", lost the send for a season)
    if _contact_site(s, memory) is not None and not _contact_sends(s):
        memory.world_seen["contact_said"] = abs_tick(s)


def _contact_sends(s: dict) -> bool:
    """(0.105.48) Make contact goes by the World screen: the switch on, the
    sender reporting, its World button known."""
    send = _send_status(s)
    if not (player_rules(s)["send_messenger"] and send and "World" in set(str(b) for b in _l(send.get("buttons")))):
        return False
    # a run that stopped at a step lately: the rule only says so (once a season), no send
    from planner_missions import last_of_goal, interrupted, SOFT_STOPS     # (r9) 'unavailable' a soft stop too
    last = last_of_goal(send, "make_contact")
    t = last.get("tick") if isinstance(last.get("tick"), int) else None
    if (t is not None and 0 <= abs_tick(s) - t < SEND_RETRY_TICKS and last.get("result") in ("stopped", "error")
            and last.get("reason") not in SOFT_STOPS and not interrupted(last)):
        return False
    return True


def note_contact_sent(p, r: dict, state: dict, memory) -> None:
    """(0.105.48, K9) planner.record: a Make contact send the bridge took (or
    whose answer was lost) stamps contact_said, so the site isn't named again
    for a season; a refusal or "not now" (ok false) stamps nothing and the
    next cycle tries again."""
    a = getattr(p, "action", None) or {}
    if a.get("type") != "send_mission" or a.get("goal", "make_contact") != "make_contact":
        return
    if a.get("dry_run") or (r or {}).get("ok") is False or memory is None:
        return
    if not isinstance(getattr(memory, "world_seen", None), dict):
        memory.world_seen = {}
    memory.world_seen["contact_said"] = abs_tick(state)


# --- meetings ---------------------------------------------------------------------

def _meeting_answer_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """DF's meeting screen is open: answer it (lua/ai-diplomacy.lua
    answer_meeting) with the Rules' tribute choice. A barony's holder is the
    player's to choose on DF's screen (no way known to pick there): Needs
    you, with what the AI does meanwhile. When the button to press hasn't
    been shown to the AI, say how."""
    m = _d(_world(s).get("meeting"))
    if not m.get("open"):
        return
    if m.get("land_holder"):
        # (0.105.35) kept: the AI can't pick on DF's barony screen (no button or field
        # for it is known); unattended, the overseer leaves the screen soon instead
        ask_player(notes, "a meeting asks who should hold a barony: the AI can't pick on DF's barony screen (no "
                          "way to choose there is known to it), so it doesn't answer; unattended, it leaves the "
                          "screen after a few minutes (the meeting ends without a holder) so the game goes on")
        return
    # (0.105.48, K9) only in an unattended run (the overseer's state["unattended"]:
    # --unattended or the keeper), as the main loop's own answer: a player at
    # the game has the screen open and answers it
    if s.get("unattended") is not True:
        notes.append("DF's meeting screen is open: left to you (the AI answers it only when nobody is at the game)")
        return
    rules = player_rules(s)
    known = set(str(b) for b in _l(m.get("buttons")))
    need = "Done" if m.get("requests") else None
    if need is None and not {"Yes", "No"} <= known:
        need = "Yes and No"
    if need and not set(need.split(" and ")) <= known:
        return                     # the meetings' Needs-you (planner_society _meeting_notes) says how
    topic = m.get("topic") or "the meeting"
    action = {"type": "answer_meeting", "tribute": rules["tribute"]}
    # (0.105.41, item 8) a peace proposal answered by the Rules' `peace` (lua/ai-diplomacy.lua weighs it)
    # (sent only when a peace proposal is among the meeting's topics)
    from planner_peace import PEACE_TOPICS, civ_peace, peace_fields
    peace = ""
    if any(t in PEACE_TOPICS for t in [topic] + list(_l(m.get("topics")))):
        action.update(peace_fields(s, cfg, memory))
        ans, why = civ_peace(s, m.get("civ_id"), memory, cfg)
        peace = f"peace: {ans}, {why}; "
    if m.get("requests"):
        wishes = meeting_wishes(s, cfg)
        if wishes:
            action["wishes"] = wishes
    proposals.append(Proposal("meeting", action,
                              f"DF's meeting screen is open ({m.get('civ') or 'a diplomat'}, {topic}): answer it "
                              f"({peace}trade agreed, the tree quota kept, tribute: {rules['tribute']})", 0))


def meeting_wishes(s: dict, cfg: dict) -> list[str]:
    """The fort's wants as DF's request categories, most needed first (at
    most 8); empty: the bridge's defaults."""
    from planner_industry import trade_wants
    out: list[str] = []
    for w in trade_wants(s, cfg, max(1, int(_d(s.get("dwarves")).get("total") or 1))):
        for c in WISH_CATEGORIES.get(str(w.get("key")), ()):
            if c not in out:
                out.append(c)
    return out[:8]


# --- war and peace, tribute, the grudge list --------------------------------------

def note_grudges(s: dict, memory) -> None:
    """Keep every civilisation that has besieged the fort (memory.world_seen
    grudges: civ id -> {name, race, sieges, last_year})."""
    if memory is None:
        return
    g = memory.world_seen.setdefault("grudges", {})
    for e in _l(_world(s).get("sieges")):
        if not isinstance(e, dict) or not isinstance(e.get("id"), int):
            continue
        old = _d(g.get(str(e["id"])))
        g[str(e["id"])] = {"name": e.get("name") or old.get("name"), "race": e.get("race") or old.get("race"),
                           "sieges": max(int(e.get("n") or 0), int(old.get("sieges") or 0)),
                           "last_year": max(int(e.get("last_year") or -1), int(old.get("last_year") or -1))}


def grudge_facts(state: dict, memory) -> dict:
    """Facts for the quirks (brain/overseer.py world_facts): the sieges on the
    game's own record and the year of the last, and how many civs that
    besieged the fort it is still at war with."""
    g = _d(_seen(memory).get("grudges"))
    w = _world(state)
    civs = {c.get("id"): c for c in _l(w.get("civs")) if isinstance(c, dict)}
    out = {}
    if g:
        out["sieges_on_record"] = sum(int(_d(v).get("sieges") or 0) for v in g.values())
        last = max(int(_d(v).get("last_year") or -1) for v in g.values())
        year = _d(state.get("date")).get("year")
        if last >= 0 and isinstance(year, int):
            out["years_since_siege_on_record"] = max(0, year - last)
        if civs:
            out["grudge_civs"] = sum(1 for k in g if str(_d(civs.get(int(k))).get("relation")) in HOSTILE)
    return out


def _world_notes(s: dict, notes: list, memory=None) -> None:
    """War and peace in a line; tribute paid or taken; visitors from a civ
    at war (left alone unless hostile on the map)."""
    w = _world(s)
    if not w:
        return
    civs = [c for c in _l(w.get("civs")) if isinstance(c, dict)]
    war = [c for c in civs if c.get("relation") in HOSTILE]
    if war:
        notes.append("at war with " + ", ".join(f"{c.get('name')} ({str(c.get('race') or '?').lower()})"
                                                 for c in war[:4])
                     + (f" and {len(war) - 4} more" if len(war) > 4 else ""))
    for c in civs:
        if c.get("tribute"):
            notes.append(f"tribute: {c.get('name')} {c['tribute']} tribute"
                         + (f" ({c['tribute_season']})" if c.get("tribute_season") else ""))
        # (0.105.41, item 8) a peace offered: said by planner_peace._peace_notes (with the AI's answer)
    if int(w.get("visitors_from_hostile") or 0) > 0:
        notes.append(f"{w['visitors_from_hostile']} visitor(s) from a civilisation at war are on the map: left "
                     "alone unless they turn hostile (only a threat gets a kill order)")


def _hostile_trade_filter(s: dict, proposals: list, notes: list) -> list:
    """No trade with a civilisation at war: while every caravan here is a
    hostile civ's (or a tribute caravan), the trade actions are dropped."""
    cars = [c for c in _l(_world(s).get("caravans")) if isinstance(c, dict)]
    if not cars:
        return proposals
    friendly = [c for c in cars if not c.get("hostile") and not c.get("tribute")]
    if friendly:
        return proposals
    drop = [p for p in proposals if p.action.get("type") in TRADE_ACTIONS]
    if not drop:
        return proposals
    hostile = [c for c in cars if c.get("hostile")]
    if hostile:
        notes.append(f"the caravan from {hostile[0].get('civ')} is from a civilisation at war with the fort: "
                     "not traded with")
    return [p for p in proposals if p not in drop]


# --- goods for export ---------------------------------------------------------------

def export_wishes(s: dict, memory) -> dict:
    """The caravans' wishes (item -> {pct, civ, tick}): what the report's
    agreements ask now, over what was kept (a year)."""
    now = abs_tick(s)
    wishes = dict(_d(_seen(memory).get("export")))
    for w in _l(_world(s).get("wanted")):
        if isinstance(w, dict) and isinstance(w.get("pct"), int) and w.get("item"):
            old = _d(wishes.get(w["item"]))
            if w["pct"] >= int(old.get("pct") or 0) or now - int(old.get("tick") or 0) > TICKS_PER_DAY * 28:
                wishes[w["item"]] = {"pct": w["pct"], "civ": w.get("civ"), "tick": now}
    return {k: v for k, v in wishes.items()
            if 0 <= now - int(_d(v).get("tick") or 0) <= EXPORT_MEMORY_DAYS * TICKS_PER_DAY}


def _export_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """A caravan's trade agreement pays more for some goods (DF's buy_prices):
    the best-paid one the fort can make is ordered for the next caravan,
    while hands are idle and nothing of it is queued. Kept a year."""
    wishes = export_wishes(s, memory)
    best = sorted(((int(_d(v).get("pct") or 0), k) for k, v in wishes.items()
                   if k in EXPORT_RECIPES and int(_d(v).get("pct") or 0) >= EXPORT_MIN_PCT), reverse=True)
    if not best or young_fort(s, cfg):
        return
    dw = _d(s.get("dwarves"))
    idle = (dw.get("idle_adults") or 0) / max(1, dw.get("adults") or 1)
    if idle < cfg["idle_share"]:
        return
    from planner_bans import banned_items      # (0.105.41, item 8) never made for export while the nobles ban it
    banned = banned_items(s)
    for pct, item in best:
        if item in banned:
            continue
        recipe = EXPORT_RECIPES[item]
        if queued(s, {recipe}):
            continue
        civ = _d(wishes.get(item)).get("civ")
        proposals.append(Proposal("export", {"type": "work_order", "recipe": recipe, "amount": EXPORT_AMOUNT},
                                  f"{civ or 'a caravan'}'s trade agreement pays {pct}% for "
                                  f"{item.lower().replace('_', ' ')}: make {EXPORT_AMOUNT} for the next caravan", 6, True))
        return


# --- 13b: the messenger and Make contact ----------------------------------------------

def _messenger_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """The fort has a messenger's post and nobody holds it: appoint a
    talker who isn't a soldier, staff, a patient or another office's holder
    (lua/ai-nobles.lua). Not in a young fort."""
    rules = player_rules(s)
    # (0.105.47) with the messenger sent by the World screen (send_messenger),
    # a young fort appoints one too: Make contact waits for nobody else
    if not rules["make_contact"] or not rules["appoint_nobles"] or (young_fort(s, cfg) and not rules["send_messenger"]):
        return
    offices = _d(s.get("offices"))
    o = _d(_d(offices.get("offices")).get("MESSENGER"))
    # (r10 p2) why nobody carries the fort's word, as the bridge read it (lua/ai-nobles.lua
    # messenger_status: "no post until population N (now M)", "post exists, nobody appointed", ...)
    why = _d(offices.get("messenger")).get("why") or _d(_d(s.get("missions")).get("messenger")).get("why")
    if not o:
        if why:
            notes.append(f"Make contact is on, but no messenger can be appointed yet: {why}")
        # (r2 h9) DF's civilisation gives this fort no messenger at all: said plainly
        elif _d(offices.get("messenger")).get("position") is False:
            notes.append("Make contact is on, but this fort's civilisation has no messenger position (DF's "
                         "nobles screen shows none): no messenger can be appointed or sent")
        return
    # (r2 h9) a messenger with no slot yet (DF's AS_NEEDED post: the nobles
    # screen adds one when it is filled): the appointment adds it
    no_slot = bool(o.get("no_slot")) and int(o.get("slots") or 0) == 0
    if _l(o.get("held")) or (int(o.get("vacant") or 0) <= 0 and not no_slot):
        return
    if o.get("appointable") is False:
        notes.append(f"Make contact is on, but the messenger is not the fort's to appoint "
                     f"({o.get('not_why') or 'DF says so'}): it waits for whoever appoints it")
        return
    # (r11 n1, the player 22 Nov 01:43) nobody free is suitable (a tiny fort's
    # founders all hold offices): an office holder doubles as messenger meanwhile
    # (the least needed office, the best talker: lua/ai-nobles.lua pick_interim),
    # swapped out once a free one is suitable (planner_office_swap); no
    # proposal at all when no interim is possible either (it was refused 4-5
    # times in each fort, 22 Nov)
    ms = _d(offices.get("messenger"))
    if str(why or "").startswith("post exists, nobody suitable"):
        if ms.get("interim_possible") and cfg.get("n1_messenger_interim", True):
            who = ms.get("interim_name") or "an office holder"
            office = str(ms.get("interim_office") or "another office").lower().replace("_", " ")
            proposals.append(Proposal("messenger", {"type": "appoint", "office": "MESSENGER", "interim": True},
                                      f"nobody free is suitable to be the messenger (every grown citizen holds an "
                                      f"office or must stay home): {who}, the {office}, doubles as messenger for "
                                      "now, until a suitable dwarf is free (Make contact needs one)", 5))
        else:
            notes.append(f"Make contact is on, but nobody can be the messenger: {why}; no office holder may double "
                         "as messenger either (only the bookkeeper, broker, sheriff, captain of the guard, chief "
                         "medical dwarf or manager, healthy and outside the squads)")
        return
    proposals.append(Proposal("messenger", {"type": "appoint", "office": "MESSENGER"},
                              "the fort has a messenger's post and nobody holds it: appoint a good talker who "
                              "isn't needed at home (Make contact needs one)"
                              + ("; DF's nobles screen adds the slot as one is appointed: the AI does the same"
                                 if no_slot else ""), 5))


def _messenger_out(ms: dict) -> list:
    """The Diplomacy controllers out, but (0.105.39 review 2) one the
    messenger's stopped run left behind (its id in the outcome's left_ids):
    a leftover never blocks Make contact for good."""
    from planner_missions import last_of_goal
    left = set(_l(last_of_goal(_d(_d(ms).get("send")), "make_contact").get("left_ids")))
    return [c for c in _l(_d(ms).get("controllers")) if isinstance(c, dict) and c.get("goal") == "DIPLOMACY"
            and c.get("id") not in left]


def _contact_site(s: dict, memory) -> dict | None:
    """The site to name for Make contact now, or None: the switch on, the
    messenger home (no Diplomacy mission out), no threat, siege, alarm,
    crisis or World screen of the player's, and the site the contact plan
    picks (brain/planner_contact.py, r10 p3: initial contact first, then by
    the fort's character and the situation), not named within its gap.
    The site comes back with `_why`, `_kind` and `_gap` (ticks)."""
    if not player_rules(s)["make_contact"]:
        return None
    ms = _d(s.get("missions"))
    if _messenger_out(ms):
        return None
    o = _d(_d(_d(s.get("offices")).get("offices")).get("MESSENGER"))
    if not _l(o.get("held")):
        return None
    from planner_contact import contact_hold, contact_plan
    if reachable_threats(s, _traits(s), PLANNER_CONFIG) or contact_hold(s, memory, PLANNER_CONFIG):
        return None
    # not in contact: DF's NoContact, or no diplomacy state at all (never met);
    # (0.105.47) never a site DF said is INACCESSIBLE (remembered) or on
    # another landmass (the report's `inaccessible`); (r9) DF's NO_CIV & co;
    # (r10 p3) only sites people live in, and the book's failures never again
    plan_ = contact_plan(s, memory, PLANNER_CONFIG)
    site = plan_.get("site")
    if site is None:
        return None
    now = abs_tick(s)
    gap = int(plan_.get("gap_days") or 14) * TICKS_PER_DAY
    said = _seen(memory).get("contact_said")
    if isinstance(said, int) and 0 < now - said < gap:     # (named this cycle: said)
        return None
    from planner_contact import last_sent_tick
    sent = last_sent_tick(memory)                           # (r10 p3) the book's last send paces it too
    if sent is not None and 0 <= now - sent < gap:
        return None
    return dict(site, _why=plan_.get("why"), _kind=plan_.get("kind"), _gap=gap)


def _send_status(s: dict) -> dict:
    """(0.105.24) The World-screen sender's state (lua/ai-mission-send.lua,
    the `missions` report's `send`): {running, last, buttons, on}."""
    return _d(_d(s.get("missions")).get("send"))


SEND_RETRY_TICKS = TICKS_PER_YEAR   # a run that stopped: not tried again for a year (the player records the rest)


def _contact_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """(13b) A site not in contact, nearest first, for "Make contact" once
    the messenger is home, no Diplomacy mission is out and no threat or
    siege is near; the mission's way out and back watched in `missions`.
    (0.105.24) With the Rules switch send_messenger on, the AI sends it
    itself by driving DF's World screen (one run at a time; a run that
    stopped at a step nobody has recorded yet isn't tried again for a year,
    and says what to record); off, it names the site for the player."""
    rules = player_rules(s)
    if not rules["make_contact"]:
        return
    ms = _d(s.get("missions"))
    from planner_missions import last_of_goal, interrupted, retry_ticks
    out = _messenger_out(ms)      # (0.105.39 review 2) a leftover of a stopped run isn't the messenger out
    if out:
        c = out[0]
        from planner_missions import departure_words
        dw = departure_words(s, c, cfg)          # (0.105.47) set up, not yet left
        if dw:
            notes.append(f"the messenger's mission to {c.get('site') or 'a site'} (Make contact) is {dw}: "
                         "one mission at a time")
            return
        notes.append(f"the messenger is {'on the way home from' if c.get('returning') else 'away to'} "
                     f"{c.get('site') or 'a site'} (Make contact): one mission at a time")
        return
    send = _send_status(s)
    running = _d(send.get("running"))
    if running:
        notes.append(f"the messenger is being sent (World screen, step {running.get('step')}): one at a time")
        return
    o = _d(_d(_d(s.get("offices")).get("offices")).get("MESSENGER"))
    if not _l(o.get("held")):
        return
    from planner_contact import contact_book, contact_hold, contact_plan
    book = contact_book(memory)
    if book.get("initial_done") is not None and book.get("initial_done") == abs_tick(s) and book.get("initial_words"):
        notes.append(str(book["initial_words"]))            # (r10 p3) said the cycle it happened
    hold = ("a threat is near" if reachable_threats(s, _traits(s), cfg) else "") or contact_hold(s, memory, cfg)   # (r10 p3) a threat, a siege, the alarm, a crisis, the player's World screen
    if hold:
        if any(isinstance(x, dict) and x.get("relation") in ("NoContact", "unknown")
               for x in _l(_d(ms.get("sites")).get("nearest"))):
            notes.append(f"a site waits for Make contact, but not while {hold}")
        return
    # (0.105.39 review) the messenger's own last run (the sender keeps one per
    # goal: a rescue's run never hides it); an older bridge's single `last`
    # only when it was Make contact's
    last = last_of_goal(send, "make_contact")
    now = abs_tick(s)
    last_tick = last.get("tick") if isinstance(last.get("tick"), int) else None
    recent = last_tick is not None and 0 <= now - last_tick < SEND_RETRY_TICKS
    blocked = last_tick is not None and 0 <= now - last_tick < retry_ticks(last, SEND_RETRY_TICKS)
    if last.get("reason") in ("inaccessible", "unavailable"):
        pass                # (0.105.47) that site is dropped (unreachable_sites); the next one is tried
        #                     (r9) DF's NO_CIV / ALREADY_IN_CONTACT / ... too (unavailable_sites)
    elif rules["send_messenger"] and last.get("result") in ("stopped", "error") and last.get("reason") == "no_messenger":
        # (0.105.47) DF listed no messenger: the messenger rule appoints one; tried again tomorrow
        if blocked:
            notes.append("the messenger's last send found no messenger on DF's list; tried again tomorrow")
            return
    elif rules["send_messenger"] and last.get("result") in ("stopped", "error") and interrupted(last):
        # (0.105.39 review 2) the player took the game back: tried again after a day
        if blocked:
            notes.append("the messenger's last send was interrupted by the player; tried again tomorrow")
            return
    elif rules["send_messenger"] and recent and last.get("result") in ("stopped", "error"):
        # said once a season (the same cooldown as the site's name)
        if _contact_site(s, memory) is not None:
            ask_player(notes, f"Make contact (13b): the AI's try to send the messenger to "
                              f"{last.get('site') or 'site ' + str(last.get('site_id'))} stopped at the World screen's "
                              f"\"{last.get('step')}\" step: {last.get('why') or last.get('reason')}. "
                              + ("A new army controller was left behind on the World screen's missions. "
                                 if last.get("controller_left") else "")
                              + "The AI can't press a step nobody has recorded (DFHack can't make the mission "
                              "itself): the messenger stays home and the AI tries again in a year; a mission sent "
                              "while python brain\\probe_missions.py --watch runs records the steps for it")
        return
    site = _contact_site(s, memory)
    if site is None:
        # (r10 p3) why the messenger stays home (the character, nothing to do)
        held = contact_plan(s, memory, cfg).get("held")
        if held:
            notes.append(f"contact: {held}")
        return
    name = site.get("name") or "site " + str(site.get("id"))
    why = f": {site['_why']}" if site.get("_why") else ""
    if rules["send_messenger"] and send:
        known = set(str(b) for b in _l(send.get("buttons")))
        if "World" not in known:
            ask_player(notes, f"Make contact (13b): {name} waits, but the AI can't find DF's World button "
                              "until it has been shown it once (the mouse on it and python "
                              "brain\\probe_missions.py --here World"
                              + ("" if "Diplomacy" in known else "; then, with a site's New mission showing, "
                                 "on Diplomacy: --here Diplomacy")
                              + "): the messenger stays home meanwhile and the site is named again next season")
            return
        if last.get("result") == "sent" and recent and now - last_tick < int(site.get("_gap") or TICKS_PER_YEAR // 4):
            return          # sent within the plan's gap: its controller shows in `missions` soon
        # (0.105.47, live 17:09) the messenger must be able to walk off the map
        from planner_missions import way_out_gate
        if not way_out_gate(s, cfg, 1 if _d(ms.get("way_out")).get("messenger_blocked") else 0,
                            f"Make contact with {name}", f"make_contact {site.get('id')}", proposals, notes, memory):
            return
        proposals.append(Proposal("contact", {"type": "send_mission", "goal": "make_contact", "site_id": site.get("id")},
                                  f"send the messenger ({_l(o.get('held'))[0]}) to make contact with {name} "
                                  f"({site.get('dist')} tiles away, not in contact), by the World screen{why}", 7))
        return
    # (0.105.35) kept: DFHack can't make a mission. (0.105.47) The World
    # screen's steps were all recorded on 14 Nov. (r10 p3) the switch is on by
    # default: this is the player's own "off"
    ask_player(notes, f"Make contact (13b): the messenger ({_l(o.get('held'))[0]}) could go to "
                      f"{name} ({site.get('dist')} tiles away), a site not in contact{why}. DFHack can't make the "
                      "mission itself; the AI sends it by DF's World screen (every step recorded) once the Rules "
                      "tab's \"Send the messenger by the World screen\" is on: until then the messenger stays home "
                      "and the site is named again next season")
