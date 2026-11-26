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

(item11) Nothing in DF saves them, so what is left is the others. Read live
on B (24 Nov, 17 of its 20 thirst deaths insane): every one of those bodies
lay coffined, none came back as a ghost, and the fort's 1,900 "saw a dead
body" feelings were all of no strength (its stress was unmet needs); the
one thread between them was family: both insane mothers' children went mad
too, 1.3 and 1.9 years after them (no proof of cause, but kin are the
mourners DF weighs most). So the bridge lists each insane dwarf's close kin among the citizens
(`kin`), the note names them, and the troubled ones join the near-breaking
at the head of the stress care (insane_kin, through insane_risk) in the weeks
before the death. A locked "quiet room" was weighed and left out: the insane
can't be led into one, nobody grieved what they saw, and a door locked on a
wanderer would only shut out the burial.

(item7, the player's decision of 26 Nov: "Bring water to them") D lost 12
melancholy and raving dwarves to thirst in one night. DF lets no insane dwarf
drink or eat by any means (no Drink or Eat job; drink on their tile or in a
locked room is never touched; DF's carriers water only a patient resting in
bed), so drink barrels or a stockpile brought to them would change nothing.
The one way left is DFHack's own (its full-heal script's): the `insane_water`
action sets a melancholy or raving dwarf's thirst timer back to 0 once it
reaches `insane_water_thirst` (DF: dehydrated 50000, dead 75000) and the
hunger timer once it reaches `insane_water_hunger` (hungry 50000, starving
75000). A direct change of the game's numbers, not a DF job: the reason
line says so plainly, and `insane_water` False turns it off. Never a
berserk dwarf (DF's, and the soldiers'), never a catatonic one (left to the
player: the same would keep them alive, staring), never a sane one; the
bridge checks each itself. The insane are never killed by the AI. Each
row's thirst and hunger, and how often the AI has watered them, are in the
`insane` section and said in the note.

Without the `insane` section (an older bridge, the fixtures) nothing here
proposes or notes anything, and planner_moods says what it always said.
"""

from __future__ import annotations

import re

from digest import _d, _l
from planner_core import EMERGENCY, LIMIT_EXEMPT, MULTI_PER_CYCLE, NO_COOLDOWN, STEER_PROTECTED, Proposal, abs_tick

__all__ = ["INSANE_KINDS", "insane_rows", "insane_risk", "insane_kin", "hazard_words", "_insane_rule",
           "water_due", "WATER_RULE"]

# (item7) water for the insane: a life each, so an emergency rule (no action
# limit, cooldown or strategist hold), as the thirst rule is
WATER_RULE = "insane_water"
for _s in (EMERGENCY, NO_COOLDOWN, LIMIT_EXEMPT, STEER_PROTECTED, MULTI_PER_CYCLE):
    _s.add(WATER_RULE)
WATERED = ("melancholy", "raving")       # the kinds watered (lua/ai-insane.lua WATERED)
DEHYDRATED = 50000
STARVING = 75000

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
    """The citizens the stress care sees to first (planner_society): the near
    breaking (_breaking), then (item11) the troubled close kin of the living
    insane (insane_kin), each once. [] without the section."""
    out = _breaking(s, cfg)
    have = {r["id"] for r in out}
    for k in insane_kin(s, cfg):
        if k["id"] not in have:
            have.add(k["id"])
            out.append(k)
    return out


KIN_WORDS = {"mother": "their mother", "father": "their father", "child": "their child", "spouse": "their spouse",
             "lover": "their lover"}
TROUBLED = ("miserable", "very_unhappy", "unhappy")


def insane_kin(s: dict, cfg: dict) -> list:
    """(item11) The close kin (mother, father, child, spouse, lover: the
    bridge's `kin` per insane row) of the living insane who are very unhappy
    or worse, or unhappy with long-term stress `insane_kin_longterm` and up
    (the bridge's own at-risk bar): every
    kind of insanity ends in death, and a death in the family is DF's
    heaviest grief (B: both insane mothers' children went mad later too).
    The stress care sees to them in the weeks before it comes. Each row is
    the bridge's, with `kin_of` (the insane one's name) and `longterm` an
    int; the most stressed first. Off with `insane_kin_care` False."""
    if not cfg.get("insane_kin_care", True):
        return []
    lt_min = int(cfg.get("insane_kin_longterm", 25000))
    out, seen = [], set()
    for r in insane_rows(s):
        for k in _l(r.get("kin")):
            if not isinstance(k, dict) or not isinstance(k.get("id"), int) or k["id"] in seen:
                continue
            lt = k.get("longterm")
            lt = int(lt) if isinstance(lt, (int, float)) and not isinstance(lt, bool) else 0
            if k.get("stress") in TROUBLED[:2] or (k.get("stress") == "unhappy" and lt >= lt_min):
                seen.add(k["id"])
                out.append(dict(k, longterm=lt, kin_of=r.get("name") or "an insane dwarf"))
    out.sort(key=lambda k: -k["longterm"])
    return out


def _kin_words(r: dict, cfg: dict) -> str:
    """'; their kin here: Ast (their child, miserable), ...: ...' or ''."""
    kin = [k for k in _l(r.get("kin")) if isinstance(k, dict) and isinstance(k.get("id"), int)]
    if not kin:
        return ""
    troubled = insane_kin({"insane": {"list": [r]}}, cfg)
    cared = [k for k in troubled if not k.get("child")]
    parts = []
    for k in kin[:4]:
        bits = [KIN_WORDS.get(k.get("link"), "kin")]
        if isinstance(k.get("stress"), str):
            bits.append(k["stress"].replace("_", " "))
        parts.append(f"{k.get('name') or 'a dwarf'} ({', '.join(bits)})")
    more = f" and {len(kin) - 4} more" if len(kin) > 4 else ""
    if cared:
        tail = "; the stress care sees to the troubled among them first, before the death comes"
    elif troubled:
        tail = "; the troubled among them are children, whom the stress care can't reach (no room or squad of their own)"
    else:
        tail = "; none of them troubled now (the stress care steps in if they become so)"
    if cared and len(cared) < len(troubled):
        tail += " (not the children: no room or squad of their own to give)"
    return f"; their kin here, who will grieve them most: {', '.join(parts)}{more}{tail}"


def _breaking(s: dict, cfg: dict) -> list:
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


from util import int_or_none as _num  # (item7) util's helper


def _water_bars(s: dict, cfg: dict) -> tuple[int, int]:
    """(item7) The thirst and hunger from which the AI waters and feeds: the
    settings', never below the bridge's own (it refuses anyone short of it)."""
    ins = _d(s.get("insane"))
    th = int(cfg.get("insane_water_thirst", 40000))
    hu = int(cfg.get("insane_water_hunger", 65000))
    bt, bh = _num(ins.get("water_thirst")), _num(ins.get("water_hunger"))
    return max(th, bt or 0), max(hu, bh or 0)


def water_due(s: dict, cfg: dict) -> list:
    """(item7) The melancholy and raving rows whose thirst or hunger reached
    the bars (_water_bars), with the AI's water on (`insane_water`): [row].
    One the AI tried lately (`insane_water_retry_ticks`) and still due (the
    try did not take) waits for the retry. The bridge's `water_more` (the due
    past its listed rows, a fort with more than ten insane) are seen to too."""
    if not cfg.get("insane_water", True):
        return []
    th, hu = _water_bars(s, cfg)
    now = abs_tick(s)
    retry = int(cfg.get("insane_water_retry_ticks", 600))
    out, seen = [], set()
    more = [r for r in _l(_d(s.get("insane")).get("water_more")) if isinstance(r, dict)]
    for r in insane_rows(s) + more:
        if r.get("kind") not in WATERED or not isinstance(r.get("id"), int) or r["id"] in seen:
            continue
        seen.add(r["id"])
        t, h = _num(r.get("thirst")), _num(r.get("hunger"))
        if not ((t is not None and t >= th) or (h is not None and h >= hu)):
            continue
        tried = _num(r.get("water_tried"))
        if tried is not None and 0 <= now - tried < retry:
            continue
        out.append(r)
    return out


def _needs_words(r: dict, s: dict, cfg: dict) -> str:
    """(item7) '; thirst 43000 (dehydrated at 50000), hunger 12000: ...' with
    what the AI does about it; the old words with an older bridge (no timers)."""
    t, h = _num(r.get("thirst")), _num(r.get("hunger"))
    if t is None and h is None:
        return "; DF lets nobody feed or water the insane, so meanwhile nothing more can be done"
    th, hu = _water_bars(s, cfg)
    bits = []
    if t is not None:
        bits.append(f"thirst {t}" + (" (dehydrated)" if t >= DEHYDRATED else ""))
    if h is not None:
        bits.append(f"hunger {h}" + (" (starving)" if h >= STARVING else ""))
    state = ", ".join(bits)
    if not cfg.get("insane_water", True):
        return (f"; {state}: DF lets no insane dwarf drink or eat, and the AI's water for them is off "
                "(insane_water): they will die of thirst unless you turn it on")
    words = (f"; {state}: DF lets no insane dwarf drink or eat (drink beside them is never touched), so the AI "
             f"sets their thirst back to 0 directly through DFHack once it reaches {th} (dehydrated at "
             f"{DEHYDRATED}) and their hunger once it reaches {hu}: a change of the game's numbers, not a DF job")
    n = _num(r.get("watered"))
    if n:
        words += f" (done {n} time{'s' if n != 1 else ''} so far)"
    if r.get("water_error"):
        words += f"; the last try failed ({r['water_error']})"
    return words


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
                         + _needs_words(r, s, cfg)
                         + _kin_words(r, cfg) + tail)
        elif kind == "raving":
            notes.append(f"{name} has gone stark raving mad{where}: insane for good; they strip, wander and "
                         "babble, eat and drink nothing, and attack no one (no alarm is raised for them); they "
                         "ignore danger" + _doors_words(r)
                         + _needs_words(r, s, cfg)
                         + _kin_words(r, cfg) + tail)
        elif kind == "catatonic":
            notes.append(f"{name} is catatonic{where}: insane for good; they stare into space until they starve, "
                         "and DF lets nobody feed them: nothing the AI can do" + _kin_words(r, cfg) + tail)
        elif kind == "berserk":
            notes.append(f"{name} has gone berserk{where}: insane for good; the squads are sent after them and "
                         "the civilian alarm keeps the others in (the military rules)" + _kin_words(r, cfg))
    if act:
        n = len(guard_ids)
        why = (f"{n} melancholy or raving dwarf(s) near deadly ground: lock the AI's own doors between them "
               "and it while they are near" if n else "")
        if held:
            why += ("; " if why else "") + (f"{held} door(s) locked for the insane: opened again once nobody "
                                            "insane is near")
        proposals.append(Proposal("insane", {"type": "insane_guard", "units": guard_ids}, why, 1))
    due = water_due(s, cfg)
    if due:
        th, hu = _water_bars(s, cfg)
        who = "; ".join(
            f"{r.get('name') or 'a dwarf'} ({r.get('kind')}, thirst {r.get('thirst')}, hunger {r.get('hunger')})"
            for r in due[:4]) + (f" and {len(due) - 4} more" if len(due) > 4 else "")
        proposals.append(Proposal(WATER_RULE, {"type": "insane_water", "units": [r["id"] for r in due]},
                                  f"{len(due)} insane dwarf(s) nearing death of thirst or hunger: {who}; DF lets no "
                                  "insane dwarf drink or eat, so the AI sets their thirst timer (from "
                                  f"{th}) and hunger timer (from {hu}) back to 0 directly through DFHack, as "
                                  "DFHack's full-heal does: a cheat the player can turn off (insane_water False); "
                                  "never a berserk, catatonic or sane dwarf", 0))
    risk = _breaking(s, cfg)
    if risk:
        total = len(risk)
        names = "; ".join(f"{r.get('name') or 'a dwarf'} ({str(r.get('stress')).replace('_', ' ')}, long-term "
                          f"stress {r['longterm']})" for r in risk[:3])
        notes.append(f"{total} citizen(s) near breaking (long-term stress high while unhappy: a death they see "
                     f"can drive them insane): {names}; the AI's stress care sees to them first (out of the "
                     "squad, a free bedroom of their own, where it can) and the recreation burrow gives the "
                     "unhappiest time off")
