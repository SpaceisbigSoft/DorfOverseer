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
    moon cells (planner_threats); a child or the sheriff / captain of the
    guard (a punishment can kill): a note only;
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
from planner_core import Proposal, abs_tick, can_fight, player_rules

__all__ = ["killer_rows", "evidence_words", "_killer_rule", "held_killer_ids"]

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
        if r["confidence"] in ("strong", "certain") and not r.get("child") \
                and not (r.get("law") and r["kind"] == "killer"):
            out.add(r["id"])
    return out


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
    return bool(c.get("pile")) and c.get("drink") == 0


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
    if c.get("restock_wait"):
        bits.append("the doors open for the haulers again after a short wait")
    if c.get("pile_all_food"):
        bits.append("its settings did not take (it takes all food)")
    n = c.get("let_outs")
    if isinstance(n, int) and n > 0:
        bits.append(f"let out {n} time(s)")
    return "; " + ", ".join(bits)


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
        if conf == "weak":
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
        if r.get("law") and kind == "killer":
            notes.append(f"{head}: the fort's sheriff or captain of the guard (a punishment can kill): the AI "
                         "doesn't lock away the law; DF's justice judges them")
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
        # a murderer (or a cursed one with killings): locked away
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
    squadded = [i for i in cell_ids if i in held and i not in pending
                and isinstance(rows.get(i, {}).get("squad_id"), int)]
    if not cell_ids and not stale:
        return
    if pending and rooms == 0 and not any(i in held for i in pending):
        notes.append(f"{len(pending)} to lock away and no jail zone or free bedroom for a cell: the AI's rooms "
                     "come first (a jail zone is made by the justice rules)")
        if not stale:
            return
    waits = [i for i in cell_ids if i in held and _pile_waits(held[i])]
    if pending or stale or dry or squadded:
        why = []
        if pending:
            why.append(f"{len(pending)} killer(s) or vampire(s) among the fort's own: lock them in a cell")
        if squadded:
            why.append(f"{len(squadded)} locked in a cell still in a squad: out of it (and of any other burrow "
                       "or military office)")
        if stale:
            why.append(f"{len(stale)} cell(s) no longer needed: let them out")
        if waits:
            why.append(f"{len(waits)} cell(s): the cell's pile waits for drink")
        proposals.append(Proposal("killer", {"type": "killer_cell", "units": cell_ids}, "; ".join(why), 1))
