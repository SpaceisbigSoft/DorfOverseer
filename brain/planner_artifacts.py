"""(item 12) The fort's artifacts shown and kept safe.

The coverage audit (12 Nov, "should"): the artifacts the moods make lay in
the stockpiles for good. DF 50+ shows them on display furniture (a pedestal
or a display case) in a temple, library, tavern, guildhall or hall, where
they add to the place's value. Thieves come for them (the heist lockout,
planner_visitors, 0.105.24) and other civs claim them (the missions report,
0.105.39).

The `artifacts` report (lua/ai-artifacts.lua) lists the artifacts on the map
(where each is, whether it is the AI's to move: made or brought home since
the AI first looked; which other civs claim it), the display furniture (its
kind, items, whether the AI placed it, its room), the AI's own rooms that
could hold one (a location's or hall's zone in a level the AI dug: its doors,
its open ways out, whether visitors may come in) and the free pedestals and
display cases.

  * artifact_display: an artifact of the AI's lying loose goes on display in
    the AI's display furniture with room left (artifact_pedestal_holds,
    artifact_case_holds), one a cycle.
  * artifact_furniture: with none with room, a free pedestal (or display
    case) is built in the safest of the AI's rooms: shut in by doors (no open
    way out: artifact_display_need_doors), closed to visitors before open
    ones (open ones only while artifact_display_open_rooms), under a roof, a
    location before a hall, the fewest displays.
  * artifact_pedestals: with none free, stone pedestals are ordered (not
    while stone is short).
  * notes: no safe room (the artifacts stay in store), and artifacts other
    civs claim (they may send someone for them; one on display behind doors
    stays).

Never sold, melted, dumped or destroyed: lua/ai-trade.lua, ai-disposal.lua
and ai-cleanup.lua refuse an artifact themselves. The player's artifacts (in
the world before the AI first looked) and the player's rooms are never
touched. The Rules switch display_artifacts (on) turns it off.

Without an `artifacts` section (an older bridge, a failed one) nothing here
proposes or says anything.
"""

from __future__ import annotations

from digest import _d, _l, game_text
from planner_core import Proposal, queued, stone_short

__all__ = ["artifact_rooms", "display_room", "_artifact_rule", "artifacts_line", "ARTIFACT_LOCATIONS"]

ARTIFACT_LOCATIONS = ("TEMPLE", "LIBRARY", "INN_TAVERN", "GUILDHALL")
ROOM_WORDS = {"TEMPLE": "temple", "LIBRARY": "library", "INN_TAVERN": "tavern", "GUILDHALL": "guildhall",
              "DiningHall": "dining hall", "MeetingHall": "meeting hall"}


def _id(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def artifact_rooms(a: dict, cfg: dict) -> list:
    """The AI's rooms fit to show artifacts, safest first: shut in by doors
    (when artifact_display_need_doors), closed to visitors before open ones
    (open ones only while artifact_display_open_rooms), under a roof, a
    location before a hall, the fewest displays, then by zone id."""
    out = []
    for r in _l(a.get("rooms")):
        if not isinstance(r, dict) or _id(r.get("zone_id")) is None:
            continue
        if cfg["artifact_display_need_doors"] and not r.get("secure"):
            continue
        if r.get("visitors") and not cfg["artifact_display_open_rooms"]:
            continue
        out.append(r)
    out.sort(key=lambda r: (bool(r.get("visitors")), bool(r.get("outside")),
                            r.get("type") not in ARTIFACT_LOCATIONS, int(r.get("displays") or 0), r["zone_id"]))
    return out


def display_room(r: dict) -> str:
    return ROOM_WORDS.get(str(r.get("type")), "hall")


def _holds(d: dict, cfg: dict) -> int:
    return int(cfg["artifact_case_holds"] if d.get("kind") == "case" else cfg["artifact_pedestal_holds"])


def _claimed_words(r: dict) -> str:
    who = [game_text(w, 30) for w in _l(r.get("claimed_by")) if isinstance(w, str)]
    return ", ".join(who[:2])


def _artifact_rule(s: dict, cfg: dict, proposals: list, notes: list, rules_: dict) -> None:
    """(item 12) An artifact of the AI's put on display in the AI's safest
    room: on furniture with room, else furniture built there, else pedestals
    ordered. Notes for artifacts claimed by other civs and for no safe room."""
    a = _d(s.get("artifacts"))
    if not a:
        return
    arts = [r for r in _l(a.get("artifacts")) if isinstance(r, dict)]
    # claimed by other civs: said while one lies anywhere but behind doors on display
    rooms_all = {r.get("zone_id"): r for r in _l(a.get("rooms")) if isinstance(r, dict)}
    disp_all = {d.get("id"): d for d in _l(a.get("displays")) if isinstance(d, dict)}
    for r in arts:
        if not r.get("claimed_by"):
            continue
        d = disp_all.get(r.get("building_id")) if r.get("state") == "displayed" else None
        room = rooms_all.get(d.get("zone_id")) if d else None
        if room and room.get("secure"):
            continue
        notes.append(f"the artifact {game_text(r.get('name') or 'without a name', 40)} is claimed by "
                     f"{_claimed_words(r)}: they may send someone for it"
                     + ("; it goes on display behind doors when it can" if r.get("mine") else
                        " (the player's: left where it is)"))
        break
    if not rules_.get("display_artifacts", True):
        return
    loose = [r for r in arts if r.get("mine") and r.get("state") == "loose" and _id(r.get("item_id")) is not None]
    if not loose:
        return
    loose.sort(key=lambda r: (not r.get("claimed_by"), _id(r.get("id")) or 0))     # the claimed ones first
    rooms = artifact_rooms(a, cfg)
    if not rooms:
        notes.append(f"{len(loose)} of the fort's artifacts wait in store: none of the AI's temples, libraries, "
                     "taverns or halls is shut in by doors to show them in")
        return
    ok_zones = {r["zone_id"]: r for r in rooms}
    mine = [d for d in _l(a.get("displays")) if isinstance(d, dict) and d.get("ai") and _id(d.get("id")) is not None
            and d.get("zone_id") in ok_zones]
    room_left = [d for d in mine if d.get("built") and int(d.get("items") or 0) < _holds(d, cfg)]
    art = loose[0]
    name = game_text(art.get("name") or "an artifact", 40)
    if room_left:
        if not _d(a.get("api")).get("display_job", True):
            notes.append("this DF has no put-on-display job: the artifacts stay in store")
            return
        room_left.sort(key=lambda d: (rooms.index(ok_zones[d["zone_id"]]), int(d.get("items") or 0), d["id"]))
        d = room_left[0]
        room = ok_zones[d["zone_id"]]
        why = (f"{name} goes on display in the {display_room(room)} (behind doors"
               + ("" if room.get("visitors") else ", no visitors") + ")")
        if art.get("claimed_by"):
            why += f"; {_claimed_words(art)} claim it"
        proposals.append(Proposal("artifact_display", {"type": "display_artifact", "item_id": art["item_id"],
                                                       "building_id": d["id"]}, why, 7))
        return
    if any(not d.get("built") for d in mine):
        return                                          # one is being built: wait for it
    free = _d(a.get("free"))
    kind = "case" if int(free.get("case") or 0) > 0 else ("pedestal" if int(free.get("pedestal") or 0) > 0 else None)
    room = rooms[0]
    if kind:
        proposals.append(Proposal("artifact_furniture", {"type": "place_display", "zone_id": room["zone_id"],
                                                         "kind": kind},
                                  f"{len(loose)} of the fort's artifacts wait in store: a "
                                  f"{'display case' if kind == 'case' else 'pedestal'} in the "
                                  f"{display_room(room)} to show them", 7))
        return
    if queued(s, {"stone_pedestal"}) or stone_short(s, cfg["artifact_pedestal_stone_min"]):
        return
    proposals.append(Proposal("artifact_pedestals", {"type": "work_order", "recipe": "stone_pedestal",
                                                     "amount": max(1, min(cfg["artifact_pedestals_max"], len(loose)))},
                              f"{len(loose)} of the fort's artifacts wait in store and no pedestal is free: "
                              "make stone pedestals to show them on", 8, True))


def artifacts_line(s: dict) -> str:
    """The artifacts in one line for the digest; "" without the section or any artifact."""
    a = _d(s.get("artifacts"))
    c = _d(a.get("counts"))
    if not a or not int(c.get("total") or 0):
        return ""
    disp = [d for d in _l(a.get("displays")) if isinstance(d, dict)]
    line = (f"ARTIFACTS {c.get('total', 0)} on the map ({c.get('mine', 0)} the AI's) | displayed "
            f"{c.get('displayed', 0)} (in rooms open to visitors {c.get('displayed_open', 0)}) | in store "
            f"{c.get('loose', 0)} | display furniture {len(disp)} (the AI's {sum(1 for d in disp if d.get('ai'))})"
            f" | free pedestals {_d(a.get('free')).get('pedestal', 0)} cases {_d(a.get('free')).get('case', 0)}")
    if int(c.get("claimed") or 0):
        who = sorted({game_text(w, 30) for r in _l(a.get("artifacts")) if isinstance(r, dict)
                      for w in _l(r.get("claimed_by")) if isinstance(w, str)})
        line += f" | claimed by others {c['claimed']}" + (f" ({', '.join(who[:3])})" if who else "")
    return line
