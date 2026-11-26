"""(r34b) A hostile come to the map is a threat at once, seen or not.

B, 26 Nov 15:15:57 (0.105.129): the journal logged an arrival event
{hostile: true, animal: false, own_civ: false} for "Lastta Geltaram, Weregiraffe
Child" at the map's edge (x1 y4). For 76 s the AI did nothing about it: no
alarm, no gates, no near-gates burrow. DF hid it from the player (isHidden: a
night creature sneaking in, on tiles not seen), and the bridge's threat rows
(others_on_map.threats) left every hidden unit out but a great danger. At
15:17:13 it killed the tavern keeper on the surface 100 tiles from B's gates;
only then did DF say "has come!" and the squad go. E (08:16) lost a pump
operator to a Weregiraffe Child outsider, F several to werepanthers.

Now:
  * the bridge lists a hidden hostile night creature, were or ambusher as a
    threat row with `hidden` (lua get_others_on_map, sneak_threat), and an
    outsider carrying the were curse in its own form with `were_curse`;
  * a hostile arrival event (not an animal, not a great danger: those have
    their own rows, hidden_great) is kept (note_hostile_arrivals) and, while
    the bridge lists no row for it, stands in as one (merge_arrivals: in the
    plan, before the rules), `hostile_arrival_hold_ticks` at most, dropped at
    its death or once the bridge lists it;
  * a stalker (stalker: one of these, a night creature, a were in either
    form) on the surface or anywhere but the deep layers whose reach DF's walk
    groups don't deny is a threat that can reach the dwarves
    (planner_core.reachable_threats): the alarm, the gates and the squads'
    matchup in the same cycle; and the near-gates burrow keeps the civilians'
    outdoor work by the gates while one is about (planner_near_gates).
"""

from __future__ import annotations

import re

from digest import _d, _l

__all__ = ["stalker", "stalker_rows", "note_hostile_arrivals", "merge_arrivals", "arrival_layer"]

DEEP_LAYERS = ("Cavern", "MagmaSea", "Underworld")
HOLD_TICKS = 1200          # a hostile arrival stands in for its row a day at most (cfg hostile_arrival_hold_ticks)
BOOK_MAX = 20
WERE_NAME = re.compile(r",\s*Were[a-z]")


from util import is_int as _int  # (r34b) util's helper


def _deep(layer) -> bool:
    return any(str(layer or "").startswith(d) for d in DEEP_LAYERS)


def stalker(t) -> bool:
    """Is this others_on_map.threats row a stalker: hidden from the player
    (an ambusher, a night creature on tiles not seen), a were in beast form or
    by its curse, a night creature, or a hostile arrival standing in for its
    row; not caged, not down in the deep layers, and not one DF's walk groups
    say can't reach the dwarves?"""
    if not isinstance(t, dict) or t.get("caged") or t.get("can_reach_dwarves") is False:
        return False
    if _deep(t.get("layer")):
        return False
    tr = t.get("transformed")
    were = tr is True or t.get("were_curse") is True or (
        tr is None and isinstance(t.get("name"), str) and WERE_NAME.search(t["name"]) is not None)
    return bool(were or t.get("hidden") is True or t.get("ambush") is True or t.get("arrival") is True
                or "NightCreature" in _l(t.get("kinds")))


def stalker_rows(s: dict) -> list:
    return [t for t in _l(_d(s.get("others_on_map")).get("threats")) if stalker(t)]


def _book(memory) -> list:
    b = getattr(memory, "hostile_arrivals", None)
    if not isinstance(b, list):
        b = []
        try:
            memory.hostile_arrivals = b
        except AttributeError:
            pass
    return b


def _hostile_arrival(e) -> bool:
    if not isinstance(e, dict) or e.get("kind") != "arrival" or e.get("hostile") is not True:
        return False
    if e.get("own_civ") or e.get("great") or not _int(e.get("unit_id")):
        return False
    were = isinstance(e.get("name"), str) and WERE_NAME.search(e["name"]) is not None
    return not e.get("animal") or were


def note_hostile_arrivals(state: dict, memory, events: list, cfg: dict | None = None) -> int:
    """Keep the hostile arrivals of the bridge's events ({id, name, tick, x, y,
    z}); drop one at its death, once the bridge lists a threat row for it, or
    `hostile_arrival_hold_ticks` after it came. Returns how many came now."""
    d = _d(state.get("date"))
    if not (_int(d.get("year")) and _int(d.get("tick"))) or memory is None:
        return 0
    from planner_core_base import abs_tick
    now = abs_tick(state)
    hold = int((cfg or {}).get("hostile_arrival_hold_ticks", HOLD_TICKS))
    book = _book(memory)
    dead = {e.get("unit_id") for e in events or [] if isinstance(e, dict) and e.get("kind") == "death"}
    listed = {t.get("id") for t in _l(_d(state.get("others_on_map")).get("threats")) if isinstance(t, dict)
              and not t.get("arrival")}
    n = 0
    for e in events or []:
        if not _hostile_arrival(e):
            continue
        book[:] = [r for r in book if r.get("id") != e["unit_id"]]
        book.append({"id": e["unit_id"], "name": str(e.get("name") or "")[:80], "tick": now,
                     "x": e.get("x"), "y": e.get("y"), "z": e.get("z")})
        n += 1
    book[:] = [r for r in book if isinstance(r, dict) and _int(r.get("tick")) and 0 <= now - r["tick"] < hold
               and r.get("id") not in dead and r.get("id") not in listed][-BOOK_MAX:]
    return n


def arrival_layer(s: dict, z) -> str | None:
    """The layer a level is in, from the report's map layers (lua
    layers_summary: name, z_top, z_bottom): one of them, 'upper_levels' above
    them all, 'between_layers' between; None when it can't say."""
    layers = [x for x in _l(_d(s.get("map")).get("layers"))
              if isinstance(x, dict) and _int(x.get("z_top")) and _int(x.get("z_bottom"))]
    if not _int(z) or not layers:
        return None
    for x in layers:
        if x["z_bottom"] <= z <= x["z_top"]:
            return str(x.get("name"))
    if z > max(x["z_top"] for x in layers):
        return "upper_levels"
    return "between_layers"


def merge_arrivals(s: dict, memory, cfg: dict | None = None) -> list:
    """The kept hostile arrivals the bridge lists no threat row for, added
    to others_on_map.threats as rows ({id, name, arrival, hidden, hostile,
    pos, layer, transformed for a were's name, can_reach_dwarves None}); the
    rows added. Not when the others_on_map section failed."""
    if memory is None or "others_on_map" in _d(s.get("_errors")):
        return []
    o = s.get("others_on_map")
    if not isinstance(o, dict):
        return []
    from planner_core_base import abs_tick
    try:
        now = abs_tick(s)
    except Exception:  # noqa: BLE001  no date: nothing stands in
        return []
    hold = int((cfg or {}).get("hostile_arrival_hold_ticks", HOLD_TICKS))
    rows = [t for t in _l(o.get("threats")) if isinstance(t, dict)]
    have = {t.get("id") for t in rows}
    add = []
    for r in _l(getattr(memory, "hostile_arrivals", None)):
        if not isinstance(r, dict) or r.get("id") in have or not _int(r.get("tick")):
            continue
        if not 0 <= now - r["tick"] < hold:
            continue
        name = str(r.get("name") or "a hostile")
        pos = {"x": r["x"], "y": r["y"], "z": r["z"]} if all(_int(r.get(k)) for k in "xyz") else None
        row = {"id": r["id"], "name": name, "arrival": True, "hidden": True, "hostile": True,
               "pos": pos, "layer": arrival_layer(s, r.get("z")), "can_reach_dwarves": None,
               "transformed": True if WERE_NAME.search(name) else None}
        if _deep(row["layer"]):
            continue
        add.append(row)
        have.add(r["id"])
    if add:
        o["threats"] = rows + add
    return add
