"""(0.105.119 item32) A werebeast in beast form is a top threat at once.

Live 25 Nov 15:00-18:30 (fresh run): F's Wereskink visitor killed two
(15:09, 15:59): the alarm sounded, the three squads' kill orders were made
and dropped by the matchup filter ("183 not sent at ... Wereskink: the
squads free are too weak for them (0.4x, 1x needed); the gates and the
alarm hold them off meanwhile") while it was inside, killing; the squad went
only once it had changed back into a human. The Werellama Child (17:07) the
same (0.7x). A (16:33, 16:38, y253): seven werepanther citizens changed at
once; the berserk rule sent one squad a cycle (able[0]) while 54 soldiers
stood by. The alarm came down "no threat for 3 cycles" with one still loose.

Now (any were in beast form: a citizen changed, a visitor, a migrant):
  * the alarm sounds and stays up while one is loose (hazard_alert);
  * every free armed squad gets a kill order on it, whatever the Rules
    tab's attack policy, the matchup's odds or a lone-intruder's one squad
    (_military_rules, _hazard_rules, planner_holdfast._squad_matchup_filter);
  * a peaceful fort's "hide rather than draft" (planner_defence_floor
    .hidden_from) never counts it as the great danger hidden from;
  * the order comes off when it is dead or changes back: a citizen in
    dwarf form is never a target (the bridge reports `kill_spared`, the
    ids of an AI kill order it would refuse now: one of the fort's own,
    sane, in their own form), and the squad's order is given again without
    them or cleared (were_spare_rules). A citizen changed back goes to their
    cell (the threats rules, planner_threats / planner_killers).
"""

from __future__ import annotations

import re

from digest import _d, _l
from planner_core import Proposal, can_fight

__all__ = ["were_name", "were_threat_rows", "were_beasts", "were_ids", "were_alert", "were_spare_rules"]

# DF's readable name of a were in beast form: "<name>, Wereskink",
# "<name>, Werellama Child", "<name>, Werepanther Bowman"
WERE_NAME = re.compile(r",\s*Were[a-z]")


def were_name(name) -> bool:
    return isinstance(name, str) and WERE_NAME.search(name) is not None


def were_threat_rows(s: dict) -> list:
    """The threats (others_on_map: visitors, migrants, wanderers) that are a
    werebeast in beast form now: the bridge's `transformed` (their race not
    their own) or, from an older bridge, a night creature named "..., Were<x>".
    Caged or chained ones are no threat."""
    out = []
    for t in _l(_d(s.get("others_on_map")).get("threats")):
        if not isinstance(t, dict) or t.get("id") is None or t.get("caged"):
            continue
        tr = t.get("transformed")
        if tr is True or (tr is None and "NightCreature" in _l(t.get("kinds")) and were_name(t.get("name"))):
            out.append(t)
    return out


def were_beasts(s: dict) -> list:
    """Every were in beast form on the map: [{id, name, own}] (own: one of the
    fort's own, the bridge's hazards.berserk rows with `changed`)."""
    out, seen = [], set()
    for b in _l(_d(s.get("hazards")).get("berserk")):
        if isinstance(b, dict) and b.get("changed") and b.get("id") is not None and b["id"] not in seen:
            seen.add(b["id"])
            out.append({"id": b["id"], "name": b.get("name"), "own": True})
    for t in were_threat_rows(s):
        if t["id"] not in seen:
            seen.add(t["id"])
            out.append({"id": t["id"], "name": t.get("name"), "own": False})
    return out


def were_ids(s: dict) -> set:
    return {w["id"] for w in were_beasts(s)}


def were_alert(s: dict) -> str:
    """Why the alarm sounds and stays up for a visiting were in beast form
    ("" if none): one that the walk groups don't say can't reach the dwarves
    (a were breaks doors; DF's groups ignore that). The fort's own changed
    ones are hazard_alert's berserk rows already."""
    rows = [t for t in were_threat_rows(s) if t.get("can_reach_dwarves") is not False]
    if not rows:
        return ""
    name = str(rows[0].get("name") or "a werebeast")
    more = f" and {len(rows) - 1} more" if len(rows) > 1 else ""
    return f"{name}{more}: a werebeast in beast form among the dwarves"


def were_spare_rules(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """A squad whose AI kill order names one the bridge would refuse now
    (`kill_spared`: one of the fort's own, sane and in their own form: a
    were changed back, a berserk dwarf calmed): the order is given again
    without them, or cleared when nobody is left. Priority 0: not held by
    the kill-order hold (planner_holdfast._kill_hold_filter)."""
    for q in _l(_d(s.get("military")).get("squads")):
        if not isinstance(q, dict) or q.get("id") is None or not q.get("ai_orders"):
            continue
        spared = {x for x in _l(q.get("kill_spared")) if isinstance(x, int)}
        # (0.105.120) the dead or gone are no target either: E asked 228 times in 40 min
        # "none of those units is on the map and alive" for an order of dead weres
        dead = {x for x in _l(q.get("kill_dead")) if isinstance(x, int)}
        ids = {x for x in _l(q.get("kill_ids")) if isinstance(x, int)}
        if not spared and not (dead and ids and ids <= dead):
            continue
        rest = [x for x in _l(q.get("kill_ids")) if isinstance(x, int) and x not in spared and x not in dead]
        who = q.get("name") or f"squad {q['id']}"
        if rest:
            proposals.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": q["id"],
                                                       "kill": list(dict.fromkeys(rest))[:50]},
                                      f"{len(spared)} of {who}'s targets are the fort's own in their own form "
                                      f"now (changed back or calm){f', {len(dead)} dead' if dead else ''}: "
                                      "never a target, the order goes on for the others", 0, guard=True))
        else:
            proposals.append(Proposal("squad_recall", {"type": "squad_orders", "squad_id": q["id"], "clear": True},
                                      (f"{who}'s target(s) are dead or gone: the squad is called back"
                                       if not spared else
                                       f"{who}'s target(s) are the fort's own in their own form now (a were "
                                       "changed back, or calm) or dead: never a target, the squad is called back "
                                       "(a were goes to their cell)"), 0))


def free_squads(s: dict, cfg: dict) -> list:
    """The squads with an AI-free hand: able to fight, not guarding a gate,
    not on the player's own orders."""
    out = []
    for q in _l(_d(s.get("military")).get("squads")):
        if not isinstance(q, dict) or q.get("id") is None or not can_fight(q, cfg) or q.get("guarding"):
            continue
        if int(q.get("orders") or 0) > int(q.get("ai_orders") or 0):
            continue                       # the player's own orders: theirs
        out.append(q)
    return out
