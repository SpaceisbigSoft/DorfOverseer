"""(r36) A stalker inside the fort is fought at once.

B, 26 Nov 18:22:36: three hidden human heroes (an AMBUSH_HERO, artifact
thieves) were flagged as stalkers (planner_hostile_arrivals) and the
near-gates burrow went on; the swordsman was already inside, in the tavern
(x113 y145 z171), and killed the tavern keeper 13 s later while every squad
went to staggered training. No kill order went because the defence's
target list drops thieves twice over: a thief among a crowd (a tavern of
guests: `crowded_thief`, 0.105.51, E's tavern fights) is no target, and one
or two thieves alone (`_lone_thieves`) leave the reachable list empty (the
thieves rule posts a guard instead). Those rules are for a guest thief
walking about seen; a hidden one inside the walls is an ambusher among the
dwarves.

`stalkers_inside` gives the ids of the stalker rows inside the fort (the
gate scan's intruders inside, or the row's own `inside`): hidden, ambushing,
a night creature or a were by form or curse; not caged, not a great danger
(the great-hold judgement's), not a fire breather (crossbows only). The
military rules put them first among the targets, as a were in beast form
is (planner_military_weres), whatever the Rules tab's policy (never attack
gives way inside the walls: 0.105.128), the odds or a crowd round them.
"""

from __future__ import annotations

from digest import _d, _l

__all__ = ["stalkers_inside", "stalker_words"]


def stalkers_inside(s: dict, threats: dict) -> list:
    """Ids (in report order) of the stalker rows inside the fort."""
    from planner_hostile_arrivals import stalker
    from planner_holdfast import _inside_ids
    inside = _inside_ids(s)
    out = []
    for i, t in threats.items():
        if not isinstance(t, dict) or not isinstance(i, int) or isinstance(i, bool):
            continue
        if not (i in inside or t.get("inside") is True):
            continue
        if t.get("great_danger") or t.get("fire_breather") is True or t.get("caged"):
            continue
        if t.get("animal") and not t.get("transformed") and not t.get("were_curse"):
            continue        # wildlife inside is the inside-few rule's
        if stalker(t):
            out.append(i)
    return out


def stalker_words(threats: dict, ids: list) -> str:
    """" (<name> (hidden) inside the fort at xX yY zZ: ...)" for the reason text."""
    if not ids:
        return ""
    t = _d(threats.get(ids[0]))
    p = _d(t.get("pos"))
    what = ("hidden" if t.get("hidden") or t.get("ambush") else
            "a were" if t.get("transformed") or t.get("were_curse") else
            "a night creature" if "NightCreature" in _l(t.get("kinds")) else "a hostile arrival")
    at = f" at x{p.get('x')} y{p.get('y')} z{p.get('z')}" if p.get("x") is not None else ""
    more = f" and {len(ids) - 1} more" if len(ids) > 1 else ""
    return (f" ({t.get('name') or 'a stalker'} ({what}){more} inside the fort{at}: an ambusher among the "
            "dwarves is fought at once, whatever the Rules tab, the odds or a crowd round it)")
