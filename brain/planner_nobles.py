"""(0.105.41, item 1) The nobles' demands: the monarch, the capital, the land
holders (baron, count, duke), and the value each noble's rooms must reach.

DF gives each office, in its position raws, the value its holder's office,
bedroom, dining room and tomb must reach (REQUIRED_OFFICE and the rest; a
monarch's are the highest). ai-nobles.lua already hands a noble a free room
of each kind (`_noble_rooms_rule`, which kinds by Deference) and a suites
level is dug when there's none free; this reads the bridge's
`noble_demands` section (lua/ai-noble-demands.lua: each noble's title,
each room's value required and the room's own) and raises a room that
falls short, one step a cycle, the highest noble first:

  * a free statue put in the room (the petition halls are lifted to their
    tier the same way since 0.90: `place_in_zone`);
  * a room in a level the AI dug: its rock smoothed, then engraved
    (`polish_room`); the player's rooms get statues only;
  * no statue free: stone statues ordered (3), unless queued or the stone
    is short.

A room with a statue placed and not yet built (`statues_pending`) or tiles
being smoothed or engraved (`polish_pending`) waits for them: the report's
free statues still count the placed one until a dwarf takes the job. The
rule holds while a threat can reach the dwarves or a siege is on (as the
traffic rule does).

At most `noble_room_statues_max` statues go into one room; past that (and
nothing left to engrave) a note says the room wants finer furniture.
`nobles_view()` is the view: each noble, required vs actual, the plan.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (AGENDA_THEMES, Proposal, _traits, noble_room_kinds, queued, stone_short)
from planner_traffic import _danger_near

__all__ = ["noble_room_plan", "nobles_view", "_noble_value_rule", "TITLE_ORDER", "noble_rank"]

AGENDA_THEMES.setdefault("noble_value", "rooms worthy of the nobles")

TITLE_ORDER = ("monarch", "duke", "count", "baron")
OFFICE_FIRST = ("MANAGER", "MAYOR", "EXPEDITION_LEADER")     # as planner_society's: an office whatever Deference says
KIND_WORDS = {"office": "office", "bedroom": "bedroom", "dining": "dining room", "tomb": "tomb"}


def noble_rank(n: dict) -> int:
    """The monarch first, then the duke, count, baron, then the rest."""
    t = n.get("title")
    return TITLE_ORDER.index(t) if t in TITLE_ORDER else len(TITLE_ORDER)


def _kinds_given(s: dict, memory=None) -> tuple:
    traits = _traits(s) if isinstance(s.get("settings"), dict) else {}
    return noble_room_kinds(traits, memory)


def noble_room_plan(s: dict, cfg: dict, memory=None) -> list:
    """Every noble room asked for, with its plan: [{unit_id, name, title,
    kind, need, value, zone_id, status ('missing' | 'under' | 'ok'), plan
    (words), action (dict or None), is_order, given}], the highest noble
    and the widest gap first. `given`: Deference gives this kind (or it is
    the manager's or mayor's office)."""
    nd = _d(s.get("noble_demands"))
    sup = _d(s.get("supplies"))
    statues = int(sup.get("statues") or 0)
    st_max = int(cfg["noble_room_statues_max"])
    kinds = _kinds_given(s, memory)
    free = _d(_d(s.get("noble_rooms")).get("free"))
    ordered = False
    out = []
    nobles = sorted((n for n in _l(nd.get("nobles")) if isinstance(n, dict)), key=noble_rank)
    # a statue placed and not built yet is still counted free by the report
    # (until a dwarf takes the job): not offered to another room
    statues -= sum(int(r.get("statues_pending") or 0) for n in nobles for r in _l(n.get("rooms"))
                   if isinstance(r, dict))
    for n in nobles:
        positions = [str(p) for p in _l(n.get("positions"))]
        for r in _l(n.get("rooms")):
            if not isinstance(r, dict) or r.get("kind") not in KIND_WORDS:
                continue
            kind, need = r["kind"], int(r.get("need") or 0)
            given = kind in kinds or (kind == "office" and any(p in OFFICE_FIRST for p in positions))
            e = {"unit_id": n.get("unit_id"), "name": n.get("name"), "title": n.get("title"), "kind": kind,
                 "need": need, "value": None, "zone_id": r.get("zone_id"), "given": given,
                 "action": None, "is_order": False}
            if r.get("zone_id") is None:
                e["status"] = "missing"
                e["plan"] = (("a free one given" if int(free.get(kind) or 0) > 0 else "none free: a suites level")
                             if given else "not given (Deference)")
                out.append(e)
                continue
            value = int(r.get("value") or 0)
            e["value"] = value
            if value >= need:
                e["status"], e["plan"] = "ok", "worthy"
                out.append(e)
                continue
            e["status"] = "under"
            st_wait = int(r.get("statues_pending") or 0)
            pol_wait = int(r.get("polish_pending") or 0)
            if not given:
                e["plan"] = "left as it is (Deference)"
            elif statues > 0 and not st_wait and int(r.get("statues") or 0) < st_max:
                statues -= 1
                e["plan"] = "a statue put in"
                e["action"] = {"type": "place_in_zone", "zone_id": r["zone_id"], "what": "statue"}
            elif pol_wait:
                e["plan"] = f"being smoothed or engraved ({pol_wait} tiles to do)"
            elif r.get("ai_built") and int(r.get("engrave_left") or 0) > 0 and not int(r.get("smooth_left") or 0):
                e["plan"] = f"engraved ({r['engrave_left']} tiles)"
                e["action"] = {"type": "polish_room", "zone_id": r["zone_id"]}
            elif r.get("ai_built") and int(r.get("smooth_left") or 0) > 0:
                e["plan"] = f"smoothed ({r['smooth_left']} tiles), then engraved"
                e["action"] = {"type": "polish_room", "zone_id": r["zone_id"]}
            elif st_wait:
                # placed and not built yet: the free statue the report still
                # counts is the one it waits for (another would point at it too)
                e["plan"] = f"a statue being put in ({st_wait} to build)"
            elif int(r.get("statues") or 0) < st_max:
                if ordered or queued(s, {"stone_statue"}):
                    e["plan"] = "a statue, once one is made"
                elif stone_short(s, cfg["noble_statue_stone_min"]):
                    e["plan"] = "a statue, once there is stone"
                else:
                    ordered = True
                    e["plan"] = "statues ordered"
                    e["action"] = {"type": "work_order", "recipe": "stone_statue", "amount": 3}
                    e["is_order"] = True
            else:
                e["plan"] = "wants finer furniture (statues and engraving done)"
            out.append(e)
    return out


def _noble_value_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """A noble's room under the value their office asks: one step a cycle
    for the highest noble's widest gap (noble_room_plan)."""
    if "noble_demands" in _d(s.get("_errors")):
        return
    if _danger_near(s):
        return                       # a threat that can reach the dwarves, or a siege: the safety rules first
    plan = noble_room_plan(s, cfg, memory)
    under = [e for e in plan if e["status"] == "under" and e["action"]]
    if under:
        e = min(under, key=lambda e: (noble_rank(e), -(e["need"] - (e["value"] or 0))))
        who = e["name"] or "a noble"
        proposals.append(Proposal("noble_value", dict(e["action"]),
                                  f"{who}'s {KIND_WORDS[e['kind']]} is worth {e['value']} of the {e['need']} "
                                  f"their office asks: {e['plan']}", 5, e["is_order"]))
    stuck = [e for e in plan if e["status"] == "under" and e["given"] and not e["action"]
             and e["plan"].startswith("wants finer")]
    if stuck:
        e = stuck[0]
        notes.append(f"{e['name']}'s {KIND_WORDS[e['kind']]} is worth {e['value']} of the {e['need']} asked, "
                     "with every statue it may hold and its stone engraved: it wants finer furniture")


def nobles_view(s: dict, cfg: dict, memory=None) -> list:
    """The nobles in words: the capital and monarch, the land holders, and
    each noble's rooms, required against actual, with the plan."""
    nd = _d(s.get("noble_demands"))
    if not nd or "error" in nd:
        return ["  (no noble demands read" + (f": {nd.get('error')}" if nd.get("error") else "") + ")"]
    lines = []
    if nd.get("capital"):
        lines.append(f"  The monarch lives here: the fort is the capital ({nd.get('monarch')})")
    holders = [h for h in _l(nd.get("land_holders")) if isinstance(h, dict)]
    if holders:
        lines.append("  Land holders: " + ", ".join(f"{h.get('name')} ({h.get('title')})" for h in holders))
    plan = noble_room_plan(s, cfg, memory)
    for n in sorted((n for n in _l(nd.get("nobles")) if isinstance(n, dict)), key=noble_rank):
        head = f"  {n.get('name')}" + (f" [{n['title']}]" if n.get("title") else "")
        head += " - " + ", ".join(str(p).lower().replace("_", " ") for p in _l(n.get("positions")))
        k = int(n.get("mandates") or 0)
        if k:
            head += f"; {k} mandate{'s' if k != 1 else ''}"
        store = _d(n.get("storage"))
        if store:
            head += "; wants " + ", ".join(f"{v} {k2}" for k2, v in sorted(store.items()))
        lines.append(head)
        for e in plan:
            if e["unit_id"] == n.get("unit_id"):
                have = "none" if e["value"] is None else str(e["value"])
                lines.append(f"    {KIND_WORDS[e['kind']]:12s} needs {e['need']:>6}  has {have:>6}  "
                             f"{e['status']}: {e['plan']}")
    return lines or ["  no noble asks for rooms"]
