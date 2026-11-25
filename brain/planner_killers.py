"""(item3) A killer among the fort's own: what the AI does about a vampire,
a werebeast or a murderer among its citizens and residents.

Why (F, 13 Nov): 70 "bleed" deaths in the log over 16 hours looked like a
vampire at work. They were a titan's 42 victims (y257), 28 told again as
their ghosts were put to rest after DF restarted (the bridge's death_details
now says those as "died before"). This rule reads the bridge's `killers`
section (lua/ai-killers.lua): each suspect with a confidence from the game's
own facts:

  certain  the curse flag (DFHack isBloodsucker / isNightCreature, the
           BLOODSUCKER tag): a vampire or a werebeast;
  strong   two killings or more of the fort's own (not brawls, not a
           berserk or changed victim, not sparring), a death by drained
           blood, or a murder or blood-drinking crime DF holds;
  weak     one killing, or brawls only.

What the AI does (it acts itself; nothing waits for the player):
  * weak: a note, nothing more (a fist fight can kill);
  * any suspect is noted first: the AI acts only once it has been suspected
    `killer_note_ticks` (half a day) and still is;
  * a berserk one: the military rules' squads (not here); a werebeast: the
    moon cells (planner_threats); a child: a note only; the sheriff /
    captain of the guard (a punishment can kill): never locked away in
    office, but (0.105.99) two killings outside a punishment and the office
    goes to a calm free dwarf (`_law_row`);
  * a vampire: sent away when the Rules tab's "send vampires away" is on
    and they are a citizen (planner_military's expel rule); still here
    `killer_expel_wait` (a week) later, or a resident (who can't be sent
    away), a squad is sent to kill them; with no squad able, or with the
    switch off (the player keeps vampires), locked in a cell: a vampire
    neither eats nor drinks, so a cell holds them for good;
  * a murderer (strong): locked in a cell (lua/ai-killers.lua: a burrow on
    a jail zone, else a free bedroom, its doors locked once they are
    inside; let out to eat and drink when thirsty or hungry, taken back
    once fed). DF's own justice (the convict rule) still convicts them when
    their case is solved. With no room for a cell, said.
Without the `killers` section (an older bridge, the fixtures) nothing here
proposes or notes anything.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import TICKS_PER_DAY, TICKS_PER_YEAR, Proposal, abs_tick, can_fight, player_rules

__all__ = ["killer_rows", "evidence_words", "_killer_rule", "held_killer_ids", "people_killer", "note_killer_book"]

KINDS = ("vampire", "werebeast", "cursed", "killer")
CONFIDENCES = ("certain", "strong", "weak")


def killers_present(s: dict) -> bool:
    return isinstance(_d(s.get("killers")).get("list"), list)


def killer_rows(s: dict) -> list:
    return [r for r in _l(_d(s.get("killers")).get("list"))
            if isinstance(r, dict) and isinstance(r.get("id"), int) and not isinstance(r.get("id"), bool)
            and r.get("kind") in KINDS and r.get("confidence") in CONFIDENCES]


def held_killer_ids(s: dict) -> set:
    """(0.105.97) The killers the killer rule holds: every unit with a cell
    (`killers.cells`), and every strong or certain suspect among the fort's
    own (the cell may still be coming), but not a child nor the sheriff or
    captain of the guard (never locked away: a note only). No other rule may
    put one into a burrow, a squad or an office: live 23 Nov, B: the
    recreation rule added the celled Degel and Fath Shemnish to the
    recreation burrow, `appoint` made Fath (2 kills) militia captain and
    `soldier_swap` had drafted him; Degel killed again in a hospital.
    lua/ai-killers.lua `held_ids` is the bridge's same list (its last guard)."""
    k = _d(s.get("killers"))
    out = {c["unit_id"] for c in _l(k.get("cells"))
           if isinstance(c, dict) and isinstance(c.get("unit_id"), int) and not isinstance(c.get("unit_id"), bool)}
    for r in killer_rows(s):
        if (r["confidence"] in ("strong", "certain") or people_killer(r)) and not r.get("child") \
                and not (r.get("law") and r["kind"] == "killer"):
            out.add(r["id"])
    return out


def people_killer(r: dict) -> bool:
    """(0.105.112) A killer row with a person killed (no animal) in the
    look-back window, in a tantrum or a brawl, any conflict level (the lawful
    ones, a sparring or a berserk victim, are not counted by the bridge):
    `people` (lua/ai-killers.lua). Live E, 24 Nov: Diamondlenses (Melbil,
    16:35) and Dentconstruct (Medtob, 22:16) each strangled a citizen in a
    tantrum and stayed "weak" (one killing: a note only) and free."""
    n = r.get("people")
    return r.get("kind") == "killer" and isinstance(n, int) and not isinstance(n, bool) and n >= 1


def evidence_words(r: dict) -> str:
    """'killed 3 of the fort's own (Urist, Kib...), 1 by drained blood; DF
    holds 1 murder against them; curse: BLOODSUCKER'."""
    bits = []
    kills, brawls = int(r.get("kills") or 0), int(r.get("brawls") or 0)
    vic = ", ".join(str(v) for v in _l(r.get("victims"))[:3])
    if kills:
        bits.append(f"killed {kills} of the fort's own" + (f" ({vic})" if vic else ""))
    if brawls:
        bits.append(f"{brawls} died after a fight or a beating with them" + (f" ({vic})" if vic and not kills else ""))
    if r.get("drained"):
        bits.append("a victim drained of blood")
    if int(r.get("punished") or 0) and r.get("law") and not kills and not brawls:
        bits.append(f"{int(r['punished'])} convict(s) died in DF's beatings at their hands")   # (item21)
    crimes = _d(r.get("crimes"))
    if crimes:
        bits.append("DF holds " + ", ".join(f"{n} {k}" for k, n in sorted(crimes.items())) + " against them")
    tags = [t for t in _l(r.get("tags")) if isinstance(t, str)]
    if tags:
        bits.append("curse: " + ", ".join(tags[:4]))
    return "; ".join(bits) or "the game's own curse flag"


def _who(r: dict) -> str:
    who = str(r.get("name") or "a dwarf")
    return who + (" (a resident)" if r.get("resident") else "")


def _squad_for(s: dict, r: dict, cfg: dict):
    """The squad to send: one able to fight, on no AI orders, not the
    suspect's own (a vampire may be a soldier)."""
    squads = [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict) and q.get("id") is not None]
    able = [q for q in squads if can_fight(q, cfg) and not q.get("ai_orders") and q.get("id") != r.get("squad_id")]
    return able[0] if able else None


def _just_sent(memory, r: dict, s: dict, cfg: dict) -> bool:
    if memory is None:
        return False
    sent = _d(getattr(memory, "kill_sent", None))
    at = _d(getattr(memory, "kill_sent_at", None))
    now = abs_tick(s)
    for sq, ids in sent.items():
        t = at.get(sq)
        if r["id"] in _l(ids) and isinstance(t, int) and 0 <= now - t < int(cfg.get("berserk_resend_ticks", 1200)):
            return True
    return False


def _pile_waits(c: dict) -> bool:
    """(0.105.97) The cell's pile (drink and prepared meals, inside the cell
    so the killer is not let out every day; B, 23 Nov) not made yet, or
    holding no drink. A pile that could not be made (pile_error) waits for
    nothing the cell action can do: said, not proposed for."""
    if c.get("pile") is False:
        return not c.get("pile_error")
    # (0.105.97, verifier) locked and empty inside the gap between two
    # restockings (`restock_wait`): the cell action can open nothing yet, so
    # it isn't asked every cycle (the rule is an emergency one: no back-off)
    if c.get("restock_wait"):
        return False
    return bool(c.get("pile")) and (c.get("drink") == 0 or _meals_wait(c))


def _meals_wait(c: dict) -> bool:
    """(item 5) The cell's pile holds no meal while the fort has free ones
    (`fort_meals`, from lua/ai-killers.lua): waited for as drink is. Live B,
    24 Nov 16:46: Ducim's pile held 3 drink and no meal, the doors opened for
    the haulers only for drink, and he was let out hungry and killed. A fort
    with no meals (fort_meals 0, or an older bridge without the field) waits
    for none."""
    n = c.get("fort_meals")
    return bool(c.get("pile")) and c.get("food") == 0 and isinstance(n, int) and n > 0



def _larder_words(c: dict) -> str:
    """(0.105.97) The cell's pile said: what it holds, an empty one, the
    times let out."""
    if not isinstance(c, dict) or "pile" not in c:
        return ""
    if c.get("pile") is False:
        bits = [f"no pile in the cell yet ({c['pile_error']})" if c.get("pile_error")
                else "the cell's pile waits to be made"]
    elif c.get("pile_empty"):
        bits = ["the cell's pile is empty: it waits for drink"]
    else:
        bits = [f"the cell's pile holds {c.get('drink') or 0} drink and {c.get('food') or 0} meal(s)"]
        if not c.get("drink"):
            bits.append("it waits for drink")
        elif _meals_wait(c):
            bits.append(f"it waits for meals ({c['fort_meals']}+ free in the fort)")
    if c.get("meals_out"):
        bits.append("no meal has reached it: let out when hungry")
    if c.get("restock_wait"):
        bits.append("the doors open for the haulers again after a short wait")
    if c.get("pile_all_food"):
        bits.append("its settings did not take (it takes all food)")
    # (0.105.98) the settings written again while the cell stood (B, 23 Nov:
    # both piles took every food), and a pile found again by its name
    fixed = c.get("pile_fixed")
    if isinstance(fixed, int) and fixed > 0:
        bits.append(f"its settings put back to drink and meals only {fixed} time(s)")
    lost = c.get("pile_lost")
    if isinstance(lost, int) and lost > 0:
        bits.append(f"its pile went missing {lost} time(s)")
    n = c.get("let_outs")
    if isinstance(n, int) and n > 0:
        bits.append(f"let out {n} time(s)")
    return "; " + ", ".join(bits)


LAW_OFFICES = ("CAPTAIN_OF_THE_GUARD", "SHERIFF")


def _law_row(s: dict, cfg: dict, r: dict, head: str, proposals: list, notes: list) -> None:
    """(0.105.99) The sheriff or the captain of the guard among the suspects.
    Never locked away while in office (a punishment can kill: a convict's
    death by the law is counted apart, `punished`). Live B, 23 Nov
    (probes r99i11-law-*): the sheriff struck down a mechanic and the captain
    of the guard broke a strand extractor's neck with her fists in a tantrum's
    brawl (one activity, three dead; no crime, no sentence, no punishment
    queue, no jail; the two officers punched each other too). Killings like
    those, outside a punishment, LAW_KILLS (cfg law_killer_kills) or more:
    the office goes to a calm free citizen (`appoint` replace killer_out,
    lua/ai-nobles-swap.lua), after which the killer rule treats them as any
    other (a cell). Fewer: said only."""
    if not isinstance(r.get("law_kills"), int):
        # an older bridge: its kills hold the convicts' beatings too
        notes.append(f"{head}: the fort's sheriff or captain of the guard (a punishment can kill): the AI "
                     "doesn't lock away the law; DF's justice judges them")
        return
    n = r["law_kills"]
    punished = int(r.get("punished") or 0)
    pun = f"; {punished} convict(s) died of DF's punishment at their hands (lawful)" if punished else ""
    need = int(cfg.get("law_killer_kills", 2))
    # (item21) one convict dead in a beating at their hands is enough too
    beat = punished >= int(cfg.get("law_punished_kills", 1))
    if n < need and not r.get("law_killer") and not beat:
        notes.append(f"{head}: the fort's sheriff or captain of the guard; {n} killing(s) outside a punishment"
                     f"{pun}: watched (the office goes to a calmer dwarf at {need}); the AI doesn't lock away the law")
        return
    codes = [c for c in LAW_OFFICES if c in [str(x) for x in _l(r.get("law_codes"))]]
    seen = r.get("seen_ticks") if isinstance(r.get("seen_ticks"), int) else 0
    if not codes:
        notes.append(f"{head}: the fort's law ({n} killing(s) outside a punishment{pun}) by an office other "
                     "than the sheriff's or the captain of the guard's: left to DF's justice")
        return
    if not player_rules(s)["appoint_nobles"]:
        notes.append(f"{head}: {n} killing(s) outside a punishment as the fort's law{pun}; appointing is off on "
                     "the Rules tab, so the AI leaves the office as it is")
        return
    if seen < int(cfg.get("killer_note_ticks", 600)):
        notes.append(f"{head}: {n} killing(s) outside a punishment as the fort's law{pun}; the office goes to a "
                     "calmer dwarf if it still holds in half a day")
        return
    code = codes[0]
    word = code.lower().replace("_", " ")
    if n < need:
        # (item21, B and D 25 Nov) four convicts strangled in DF's beatings by the guard
        # captain and the sheriff: one death in a beating is enough to lose the post
        why = (f"the {word} beat {punished} convict(s) to death in DF's punishment: the post goes to a calm free "
               "dwarf (the fight watcher spares the beatings now; a beating's death is lawful, never a cell)")
    else:
        why = (f"the {word} killed {n} of the fort's own outside a punishment (fights, not DF's sentences){pun}: "
               "the post goes to a calm free dwarf; out of office, the killer rule holds them as any other")
    proposals.append(Proposal("law_swap", {"type": "appoint", "office": code, "replace": True, "killer_out": True,
                                           "unit_id": r["id"]}, f"{head}: {why}", 2))


def _killer_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """Each suspect said with the evidence and the confidence; the cell
    proposed for the murderers (and the vampires kept), a squad sent at a
    vampire that can't be or wasn't sent away."""
    if not killers_present(s):
        return
    k = _d(s.get("killers"))
    rules_ = player_rules(s)
    expel_on = rules_.get("expel_vampires", True) is not False
    note_ticks = int(cfg.get("killer_note_ticks", 600))
    expel_wait = int(cfg.get("killer_expel_wait", 7 * 1200))
    rooms = k.get("rooms") if isinstance(k.get("rooms"), int) else None
    cell_ids: list = []
    for r in killer_rows(s):
        who, kind, conf = _who(r), r["kind"], r["confidence"]
        ev = evidence_words(r)
        seen = r.get("seen_ticks") if isinstance(r.get("seen_ticks"), int) else 0
        what = {"vampire": "is a vampire", "werebeast": "carries a werebeast curse",
                "cursed": "carries a curse (undead-like)", "killer": "may be a murderer"}[kind]
        head = f"{who} {what} ({conf}: {ev})"
        if r.get("law") and kind == "killer":
            _law_row(s, cfg, r, head, proposals, notes)
            continue
        if conf == "weak" and not people_killer(r):
            notes.append(f"{head}: watched; one killing or a fight gone too far is not enough for the AI to "
                         "act on one of the fort's own")
            continue
        if r.get("berserk"):
            notes.append(f"{head}: berserk now; the squads are sent after them (the military rules)")
            continue
        if kind == "werebeast":
            notes.append(f"{head}: the moon cells lock them away for the full moon (the threats rules)")
            continue
        if r.get("child"):
            notes.append(f"{head}: a child; the AI locks away or sends a squad at no child")
            continue
        if seen < note_ticks:
            notes.append(f"{head}: first seen {seen // 50} hour(s) ago; the AI acts if it still holds in "
                         f"{max(1, (note_ticks - seen) // 50)} hour(s)")
            continue
        cell = _d(r.get("cell"))
        if kind == "vampire":
            if not expel_on:
                cell_ids.append(r["id"])
                notes.append(f"{head}: sending vampires away is off on the Rules tab, so the AI keeps them, locked "
                             "in a cell (a vampire neither eats nor drinks; it drinks no one's blood there)")
                continue
            if r.get("citizen") and seen < expel_wait:
                notes.append(f"{head}: the AI sends them away (Rules tab); a squad goes after them if they are "
                             "still here in a week")
                continue
            q = _squad_for(s, r, cfg)
            if _just_sent(memory, r, s, cfg):
                notes.append(f"{head}: a squad was sent after them")
            elif q is not None:
                why = ("a resident, who can't be sent away" if not r.get("citizen")
                       else "still here a week after the AI began sending them away")
                proposals.append(Proposal("killer", {"type": "squad_orders", "squad_id": q["id"], "kill": [r["id"]]},
                                          f"{head}: {why}: send {q.get('name') or 'the squad'} to kill them",
                                          1, guard=True))
            else:
                cell_ids.append(r["id"])
                notes.append(f"{head}: no squad able to fight is free, so the AI locks them in a cell meanwhile")
            continue
        # a murderer (or a cursed one with killings, or (0.105.112) one who
        # killed a citizen): locked away
        cell_ids.append(r["id"])
        larder = _larder_words(cell)
        if cell.get("locked"):
            notes.append(f"{head}: locked in a cell by the AI (let out to eat and drink, then back){larder}; DF's "
                         "justice convicts them once their case is solved")
        elif cell.get("stocking"):
            notes.append(f"{head}: in the AI's cell, its doors open for the haulers to bring drink and food in "
                         f"(the killer kept in by the cell's burrow){larder}")
        elif cell.get("out"):
            notes.append(f"{head}: let out of the AI's cell to eat and drink; back once fed")
        else:
            notes.append(f"{head}: the AI locks them in a cell (a jail zone, else a free bedroom; the doors locked "
                         "once they are inside, let out to eat and drink)")
    cells = [c for c in _l(k.get("cells")) if isinstance(c, dict) and isinstance(c.get("unit_id"), int)]
    held = {c["unit_id"]: c for c in cells}
    # (0.105.112) the ones kept though the report no longer asks: a killer
    # still in a tantrum, miserable or very unhappy, or within killer_hold_days
    # of the killing; a chronic tantrum case who attacked a citizen, held while
    # miserable (each said)
    kept = _kept_holds(s, cfg, memory, held, cell_ids)
    for i, why in kept.items():
        cell_ids.append(i)
        notes.append(why)
    stale = [u for u in held if u not in cell_ids]
    pending = [i for i in cell_ids if not held.get(i, {}).get("locked")]
    # (0.105.97) a held cell whose pile waits for drink (none made yet, or
    # none in it) keeps the cell action running: it makes the pile and opens
    # the doors for the haulers while it runs low
    dry = [i for i in cell_ids if i in held and i not in pending and _pile_waits(held[i])]
    # (0.105.97) one locked in but still a soldier (drafted before, or by the
    # player): the cell action takes them out of the squad, any military office
    # and every other burrow (lua/ai-killers.lua keep_apart; B, 23 Nov)
    rows = {r["id"]: r for r in killer_rows(s)}
    # (0.105.114) the urgent ones: locked at once, no larder wait (below)
    urgent = _urgent_holds(s, memory, cell_ids)
    dry = [i for i in dry if i not in urgent]
    for i, why in urgent.items():
        r = rows.get(i) or {}
        notes.append(f"{r.get('name') or f'unit {i}'} {why}: locked in the AI's cell at once, its doors not "
                     "opened for the haulers (drink and meals brought in once calm)")
    squadded = [i for i in cell_ids if i in held and i not in pending
                and isinstance(rows.get(i, {}).get("squad_id"), int)]
    if not cell_ids and not stale:
        return
    if pending and rooms == 0 and not any(i in held for i in pending):
        notes.append(f"{len(pending)} to lock away and no jail zone or free bedroom for a cell: the AI's rooms "
                     "come first (a jail zone is made by the justice rules)")
        if not stale:
            return
    waits = [i for i in cell_ids if i in held and _pile_waits(held[i]) and i not in urgent]
    if pending or stale or dry or squadded:
        why = []
        if pending:
            chronic = [i for i in pending if kept.get(i, "").startswith(CHRONIC_HEAD)]
            if len(chronic) < len(pending):
                why.append(f"{len(pending) - len(chronic)} killer(s) or vampire(s) among the fort's own: lock them "
                           "in a cell")
            if chronic:
                why.append(f"{len(chronic)} chronic tantrum dwarf(s) who attacked citizens: held in a cell (drink "
                           "and meals brought in) until no longer miserable")
        if squadded:
            why.append(f"{len(squadded)} locked in a cell still in a squad: out of it (and of any other burrow "
                       "or military office)")
        if stale:
            why.append(f"{len(stale)} cell(s) no longer needed: let them out")
        if waits:
            # (item 5) drink, meals or both: what the waiting piles lack
            lack = [w for w, f in (("drink", lambda c: c.get("drink") == 0), ("meals", _meals_wait))
                    if any(f(held[i]) for i in waits)]
            what = " and ".join(lack) or "drink"
            why.append(f"{len(waits)} cell(s): the cell's pile waits for {what}")
        action = {"type": "killer_cell", "units": cell_ids}
        if urgent:
            action["urgent"] = sorted(urgent)
        proposals.append(Proposal("killer", action, "; ".join(why), 1))


URGENT_KILL_TICKS = TICKS_PER_DAY


def _urgent_holds(s: dict, memory, cell_ids: list) -> dict:
    """(0.105.114) {unit id: why} of the held killers locked at once: a
    werebeast, one transformed now, one in a tantrum (or berserk), or one who
    killed a person within the last day. For them the cell's pile waits for
    nothing (the larder's doors stay shut; drink and meals come once calm);
    the larder wait is for calm cases only. Live E, 25 Nov 06:00-08:00: the
    killer_cell rule ran about every minute on Dentconstruct (a werebeast,
    certain, people 2) with "the cell's pile waits for drink and meals"; the
    doors opened for the haulers again and again, he was out of his cell 30
    of 77 cycles, killed two citizens at 08:00 and was struck down."""
    from planner_tantrums import tantrum_rows
    rows = {r["id"]: r for r in killer_rows(s)}
    tant = {r["id"]: r for r in tantrum_rows(s)}
    cells = {c["unit_id"]: c for c in _l(_d(s.get("killers")).get("cells"))
             if isinstance(c, dict) and isinstance(c.get("unit_id"), int)}
    now = _now(s)
    book = _d(_d(getattr(memory, "killer_book", None)).get("kills")) if memory is not None else {}
    out = {}
    for i in cell_ids:
        r, t, c = _d(rows.get(i)), _d(tant.get(i)), _d(cells.get(i))
        if r.get("kind") == "vampire":
            continue                       # a vampire neither eats nor drinks: nothing to wait for
        ago = r.get("last_ago")
        k = _d(book.get(str(i)))
        recent = (isinstance(ago, int) and 0 <= ago < URGENT_KILL_TICKS and int(r.get("people") or r.get("kills") or 0) > 0) \
            or (now is not None and isinstance(k.get("last"), int) and 0 <= now - k["last"] < URGENT_KILL_TICKS)
        if r.get("kind") == "werebeast":
            out[i] = "carries a werebeast curse"
        elif r.get("transformed") or c.get("urgent") == "transformed":
            out[i] = "is transformed"
        elif t.get("now") or r.get("berserk") or c.get("urgent") == "raging":
            out[i] = "is in a tantrum"
        elif recent:
            out[i] = "killed within the last day"
        elif isinstance(c.get("urgent"), str):
            out[i] = {"were": "carries a werebeast curse"}.get(c["urgent"], "is not calm")
    return out


# --- (0.105.112) who stays held ------------------------------------------------

CHRONIC_HEAD = "chronic tantrum case"
UNHAPPY = ("miserable", "very_unhappy")
STRESS_WORDS = {0: "miserable", 1: "very_unhappy"}


def note_killer_book(s: dict, memory) -> dict:
    """The citizens who killed a citizen (`people` rows: the newest killing's
    tick) and the citizens who attacked one (the fight watcher's `attack` and
    `tantrum_ended` log rows), kept in memory.killer_book: the report forgets
    a killing once it is older than its window (3 game years: ~7 real hours
    in E, whose year runs in ~2.4) and the watcher's log is lost with the game
    (a reload, the 3-hourly fresh start). Kept a year. Returns the book."""
    now = _now(s)
    if memory is None or now is None:
        return {}
    book = dict(_d(getattr(memory, "killer_book", None)))
    kills = {k: v for k, v in _d(book.get("kills")).items() if isinstance(v, dict) and isinstance(v.get("last"), int)
             and 0 <= now - v["last"] < TICKS_PER_YEAR}
    for r in killer_rows(s):
        ago = r.get("last_ago")
        # (0.105.114) a werebeast who killed a person is booked too: a cell he
        # is in stays (E, 25 Nov: Dentconstruct, booked as a killer, then read
        # as a werebeast)
        were_kill = r.get("kind") == "werebeast" and isinstance(r.get("people"), int) \
            and not isinstance(r.get("people"), bool) and r["people"] >= 1
        if (people_killer(r) or were_kill) and isinstance(ago, int) and not r.get("child") and not r.get("law"):
            last = now - ago
            old = _d(kills.get(str(r["id"])))
            if not isinstance(old.get("last"), int) or old["last"] < last:
                kills[str(r["id"])] = {"last": last, "name": str(r.get("name") or "")[:60]}
    attacks = {}
    for k, v in _d(book.get("attacks")).items():
        ts = [t for t in _l(v) if isinstance(t, int) and 0 <= now - t < TICKS_PER_YEAR]
        if ts:
            attacks[k] = ts
    for e in _l(_d(s.get("fights")).get("log")):
        if not isinstance(e, dict) or e.get("kind") not in ("attack", "tantrum_ended"):
            continue
        i, t = e.get("id"), e.get("tick")
        if not (isinstance(i, int) and isinstance(t, int) and isinstance(e.get("target"), int)) or t > now:
            continue
        ts = attacks.setdefault(str(i), [])
        if t not in ts:
            ts.append(t)
            ts.sort()
            del ts[:-10]
    book["kills"], book["attacks"] = kills, attacks
    memory.killer_book = book
    return book


def _now(s: dict):
    d = _d(s.get("date"))
    return abs_tick(s) if isinstance(d.get("year"), int) and isinstance(d.get("tick"), int) else None


def _stress_of(r: dict | None, t: dict | None):
    """'miserable', 'very_unhappy', ... from the killer row's stress category
    (0 miserable, 1 very unhappy) or the tantrum ledger row's word."""
    v = _d(r).get("stress")
    if isinstance(v, int) and not isinstance(v, bool):
        return STRESS_WORDS.get(v, "calmer")
    w = _d(t).get("stress")
    return w if isinstance(w, str) and w else None


def _kept_holds(s: dict, cfg: dict, memory, held: dict, cell_ids: list) -> dict:
    """{unit id: the words}: the ones held in (or put into) a cell though the
    killer list doesn't ask for them. A killer with a cell (not the law, not a
    child): kept while in a tantrum, miserable or very unhappy, or within
    killer_hold_days of the last killing of a citizen. A chronic tantrum case
    (chronic_tantrums+ this year) who attacked a citizen in the last
    chronic_hold_attack_days: held (a cell is made) while miserable or in a
    tantrum. Live E, 24 Nov: Muterazor, celled at 20:29, was let out "no longer
    needed" at 20:35 (year 270, tick 65088) when his killings of 267 (tick
    61328, 62769) passed the 3-year window; he strangled Thikut at 21:31."""
    from planner_tantrums import tantrum_rows
    now = _now(s)
    if now is None:
        return {}
    book = note_killer_book(s, memory)
    rows = {r["id"]: r for r in killer_rows(s)}
    tant = {r["id"]: r for r in tantrum_rows(s)}
    out = {}
    hold = int(cfg.get("killer_hold_days", 56)) * TICKS_PER_DAY
    for i in held:
        if i in cell_ids:
            continue
        r = rows.get(i)
        if r is not None and (r.get("law") or r.get("child")):
            continue                                  # the law and children: the rules above say
        t = tant.get(i)
        k = _d(_d(book.get("kills")).get(str(i)))
        if not k and not (t and int(t.get("year") or 0) >= int(cfg.get("chronic_tantrums", 3))):
            continue
        who = (r or t or {}).get("name") or k.get("name") or f"unit {i}"
        stress = _stress_of(r, t)
        if k:
            days = (now - k["last"]) // TICKS_PER_DAY if isinstance(k.get("last"), int) else None
            why = ("is in a tantrum" if _d(t).get("now") else f"is {stress.replace('_', ' ')}" if stress in UNHAPPY
                   else f"did so {days} day(s) ago" if days is not None and now - k["last"] < hold else None)
            if why:
                out[i] = (f"{who} killed a citizen and {why}: kept in the AI's cell (never let out while in a "
                          f"tantrum, miserable or very unhappy, nor within {hold // TICKS_PER_DAY} days of the killing)")
            continue
        if _d(t).get("now") or stress == "miserable":
            out[i] = (f"{CHRONIC_HEAD}: {who} ({t.get('year')} tantrums this year, "
                      f"{'in a tantrum' if t.get('now') else 'miserable'}) attacked a citizen: kept in the AI's cell "
                      "until no longer miserable")
    # the chronic attackers not held yet
    attack_win = int(cfg.get("chronic_hold_attack_days", 336)) * TICKS_PER_DAY
    for i, t in tant.items():
        if i in held or i in cell_ids or i in out or int(t.get("year") or 0) < int(cfg.get("chronic_tantrums", 3)):
            continue
        if not (t.get("now") or t.get("stress") == "miserable") or t.get("child"):
            continue
        ts = [x for x in _l(_d(book.get("attacks")).get(str(i))) if isinstance(x, int) and 0 <= now - x < attack_win]
        if not ts:
            continue
        out[i] = (f"{CHRONIC_HEAD}: {t.get('name') or i} threw {t.get('year')} tantrums this year, is "
                  f"{'in a tantrum' if t.get('now') else 'miserable'} and attacked a citizen "
                  f"{(now - ts[-1]) // TICKS_PER_DAY} day(s) ago (the fight watcher saw it): held in the AI's cell "
                  "(drink and meals brought in) until no longer miserable")
    return out
