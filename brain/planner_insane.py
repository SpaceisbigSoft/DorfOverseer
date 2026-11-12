"""(0.105.40b) The fort's insane, and the citizens heading that way.

DF (DF wiki, Insane, v50): insanity, from a strange mood that failed or from
stress past breaking, is permanent; the insane don't sleep, eat, drink,
follow orders or work, and every kind ends in death:

  * melancholy: moves slowly and seeks death (a jump, water, magma); with
    none to hand, thirst or hunger;
  * stark raving mad (mood Raving): strips, wanders, babbles; attacks no one
    and doesn't seek death, but ignores danger; thirst or hunger;
  * berserk: attacks everyone (planner_military's berserk rule and the
    civilian alarm: not here);
  * catatonic (mood Traumatized): stares until they starve.

DF lets nobody feed or water the insane (its doctors water only patients in
bed). What the AI can do (lua/ai-insane.lua, the `insane` report section
and the `insane_guard` action): say who, what kind, where and what deadly
ground (deep water, magma, a drop) lies near; lock its own doors (never a
hatch, a gate's, a lever's, a werebeast cell's or the cavern seal's) that
truly stand between a melancholy or raving dwarf and that ground (no other
way round, no sane citizen on the far side) while they are near (a locked
door stops everyone but a building destroyer), freeing each as soon as they
move off (the report frees the stale ones itself, so a lock never outlasts
a halted AI); and, before it comes to that, put the citizens whose
long-term stress is near breaking first in the stress care
(planner_society._stress_care). Their room and things go back to the fort
when they die (DF, and the rules for the dead).

Without the `insane` section (an older bridge, the fixtures) nothing here
proposes or notes anything, and planner_moods says what it always said.
"""

from __future__ import annotations

import re

from digest import _d, _l
from planner_core import Proposal

__all__ = ["INSANE_KINDS", "insane_rows", "insane_risk", "hazard_words", "_insane_rule"]

INSANE_KINDS = ("melancholy", "raving", "berserk", "catatonic")
GUARDED = ("melancholy", "raving")
INSANE_MOODS = {"Melancholy", "Raving", "Berserk", "Traumatized"}   # df.mood_type, as the moods list says them
HAZARD_NAMES = {"water": "deep water", "magma": "magma", "drop": "a drop of two levels or more"}


def insane_present(s: dict) -> bool:
    """The bridge sent the `insane` section (a list, empty or not)."""
    return isinstance(_d(s.get("insane")).get("list"), list)


def insane_rows(s: dict) -> list:
    return [r for r in _l(_d(s.get("insane")).get("list"))
            if isinstance(r, dict) and r.get("kind") in INSANE_KINDS]


def insane_ids(s: dict) -> set:
    return {r.get("id") for r in insane_rows(s)}


def insane_risk(s: dict, cfg: dict) -> list:
    """The citizens near breaking (DF wiki, Stress: insanity comes when both
    the long-term and the short-term stress are high): long-term stress
    `insane_risk_longterm` and up while very unhappy or worse, or
    `insane_risk_harrowed` and up while unhappy or worse; the most first.
    [] without the section."""
    lt_min = int(cfg.get("insane_risk_longterm", 50000))
    harrowed = int(cfg.get("insane_risk_harrowed", 100000))
    out = []
    for r in _l(_d(s.get("insane")).get("at_risk")):
        if not isinstance(r, dict) or r.get("id") is None or not isinstance(r.get("longterm"), int):
            continue
        st = r.get("stress")
        if ((r["longterm"] >= lt_min and st in ("miserable", "very_unhappy"))
                or (r["longterm"] >= harrowed and st in ("miserable", "very_unhappy", "unhappy"))):
            out.append(r)
    out.sort(key=lambda r: -r["longterm"])
    return out


def hazard_words(h: dict) -> str:
    """'deep water 4 tiles away, magma 9 tiles away', the nearest first."""
    rows = sorted((d, k) for k, d in _d(h).items() if k in HAZARD_NAMES and isinstance(d, int))
    return ", ".join(f"{HAZARD_NAMES[k]} {d} tile{'s' if d != 1 else ''} away" for d, k in rows)


def _place(r: dict) -> str:
    p = r.get("place")
    if not isinstance(p, str) or not p:
        return ""
    return " (in the " + re.sub(r"(?<!^)(?=[A-Z])", " ", p).lower() + ")"


def _doors_words(r: dict) -> str:
    hz = hazard_words(_d(r.get("hazards")))
    locked = int(r.get("locked") or 0)
    doors = int(r.get("doors") or 0)
    if not hz:
        return ("; no deadly ground near them now: the AI locks its own doors between them and any they "
                "come near")
    if locked or doors:
        n = locked + doors
        return (f"; {hz}: the AI locks {n} of its own door{'s' if n != 1 else ''} between them and it while "
                "they are near, and opens them again as they move off (two days at most at a time, so nobody "
                "stays shut in)")
    return (f"; {hz}, and no door of the AI's own stands between to lock (it locks only doors it built that "
            "alone shut the way, never a hatch, a gate, a lever's, a cell's, the cavern seal's or one already "
            "locked)")


def _insane_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """Each insane citizen said with their kind, where, the deadly ground
    near them and what the AI does; the guard proposed while a melancholy or
    raving one has an AI door between them and deadly ground, or locks are
    held (to free them); the near-breaking said with what the AI does."""
    ins = _d(s.get("insane"))
    if not insane_present(s):
        return
    rows = insane_rows(s)
    guard_ids = [r["id"] for r in rows if r.get("kind") in GUARDED and isinstance(r.get("id"), int)]
    held = int(ins.get("locks") or 0)
    act = held > 0 or any(r.get("kind") in GUARDED and int(r.get("doors") or 0) > 0 for r in rows)
    for r in rows:
        name, kind = r.get("name") or "a dwarf", r.get("kind")
        where = _place(r)
        tail = "; their room and things go back to the fort when they die"
        if kind == "melancholy":
            notes.append(f"{name} has fallen into melancholy{where}: insane for good (DF has no cure); they eat "
                         "and drink nothing and seek death in water, magma or a fall" + _doors_words(r)
                         + "; DF lets nobody feed or water the insane, so meanwhile nothing more can be done"
                         + tail)
        elif kind == "raving":
            notes.append(f"{name} has gone stark raving mad{where}: insane for good; they strip, wander and "
                         "babble, eat and drink nothing, and attack no one (no alarm is raised for them); they "
                         "ignore danger" + _doors_words(r)
                         + "; DF lets nobody feed or water the insane, so meanwhile nothing more can be done"
                         + tail)
        elif kind == "catatonic":
            notes.append(f"{name} is catatonic{where}: insane for good; they stare into space until they starve, "
                         "and DF lets nobody feed them: nothing the AI can do" + tail)
        elif kind == "berserk":
            notes.append(f"{name} has gone berserk{where}: insane for good; the squads are sent after them and "
                         "the civilian alarm keeps the others in (the military rules)")
    if act:
        n = len(guard_ids)
        why = (f"{n} melancholy or raving dwarf(s) near deadly ground: lock the AI's own doors between them "
               "and it while they are near" if n else "")
        if held:
            why += ("; " if why else "") + (f"{held} door(s) locked for the insane: opened again once nobody "
                                            "insane is near")
        proposals.append(Proposal("insane", {"type": "insane_guard", "units": guard_ids}, why, 1))
    risk = insane_risk(s, cfg)
    if risk:
        total = len(risk)
        names = "; ".join(f"{r.get('name') or 'a dwarf'} ({str(r.get('stress')).replace('_', ' ')}, long-term "
                          f"stress {r['longterm']})" for r in risk[:3])
        notes.append(f"{total} citizen(s) near breaking (long-term stress high while unhappy: a death they see "
                     f"can drive them insane): {names}; the AI's stress care sees to them first (out of the "
                     "squad, a free bedroom of their own, where it can) and the recreation burrow gives the "
                     "unhappiest time off")
