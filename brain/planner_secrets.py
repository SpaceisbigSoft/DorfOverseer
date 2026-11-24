"""(0.105.95) The secrets of life and death: the AI decides whether the fort
keeps them.

Live 23 Nov: C and F hold the artifact slab "Kuluruxen, Nightsearch" (the
Secrets). A slab can't be read in fortress mode, so it is kept (its value on
display) and said once a report. A book or scroll carrying the secret makes
its reader a necromancer, and the corpses a citizen necromancer raises are
hostile to all life (only dead citizens raised as intelligent undead stay
citizens): a danger a weak or peaceful fort can't carry, a dark power a war
fort may choose. So, by the fort's own character (the player's rule: the AI
decides every case):

  * Militarism MILITANT or more and SOLDIERS or more soldiers in the squads:
    the fort keeps its secrets books (let go if the AI forbade them), and its
    necromancers are watched like any citizen;
  * else each secrets book or scroll is forbidden, so nobody takes it to read.

Necromancers already in the fort are said either way (the undead rules meet
what they raise).
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import Proposal

MILITANT = 50          # Militarism slider value from which a fort may choose necromancy
SOLDIERS = 20          # ...with at least this many soldiers to meet what is raised


def _soldiers(s: dict) -> int:
    n = 0
    for q in _l(_d(s.get("military")).get("squads")):
        if isinstance(q, dict) and isinstance(q.get("members"), int) and not isinstance(q.get("members"), bool):
            n += q["members"]
    return n


def keeps_secrets(s: dict) -> tuple[bool, str]:
    """Whether this fort keeps the secrets of life and death, and why."""
    traits = _d(_d(s.get("settings")).get("traits"))
    mil = traits.get("militarism")
    mil = mil if isinstance(mil, (int, float)) and not isinstance(mil, bool) else 0
    soldiers = _soldiers(s)
    if mil >= MILITANT and soldiers >= SOLDIERS:
        return True, f"a war fort (Militarism {mil:g}, {soldiers} soldiers) can master what the dead become"
    why = (f"Militarism {mil:g}" + (f" (under {MILITANT})" if mil < MILITANT else "")
           + f", {soldiers} soldier(s)" + (f" (under {SOLDIERS})" if soldiers < SOLDIERS else ""))
    return False, f"too weak or too peaceful to live beside the raised dead ({why})"


def secrets_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    sec = _d(_d(s.get("artifacts")).get("secrets"))
    if not sec:
        return
    slabs = sec.get("slabs") if isinstance(sec.get("slabs"), int) else 0
    books = [b for b in _l(sec.get("books")) if isinstance(b, dict) and isinstance(b.get("id"), int)]
    necros = [n for n in _l(sec.get("necromancers")) if isinstance(n, dict)]
    if slabs:
        notes.append(f"{slabs} slab(s) of the secrets of life and death: kept (a slab can't be read in a fort; "
                     "only a book or scroll makes a necromancer)")
    if necros:
        notes.append(f"{len(necros)} necromancer(s) on the map: " + ", ".join(
            f"{n.get('name')}" + (" (a citizen)" if n.get("citizen") else "") for n in necros[:3])
            + "; what they raise is hostile to all life (dead citizens raised keep their place)")
    if not books:
        return
    keep, why = keeps_secrets(s)
    if keep:
        free = [b["id"] for b in books if b.get("forbidden")]
        notes.append(f"{len(books)} book(s) of the secrets of life and death kept: {why}")
        if free:
            proposals.append(Proposal("secrets", {"type": "forbid_secrets", "ids": free[:20], "on": False},
                                      f"{len(free)} forbidden book(s) of the secrets of life and death let go: {why}", 4))
        return
    shut = [b["id"] for b in books if not b.get("forbidden")]
    if shut:
        names = ", ".join(str(b.get("name") or b["id"]) for b in books[:2])
        proposals.append(Proposal("secrets", {"type": "forbid_secrets", "ids": shut[:20], "on": True},
                                  f"{names}: the secrets of life and death; forbidden so nobody reads them and "
                                  f"turns necromancer: {why}", 2))
