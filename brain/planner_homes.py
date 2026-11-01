"""planner_homes (0.104.168): one bedroom per household, and rooms the stressed like.

From the report's `homes` section (lua/ai-homes.lua census, once a game day):

* a couple in two rooms (each spouse kept the one they had before the
  wedding; DF has married couples share one room and one bed), a couple whose
  room is in only one spouse's list, a dwarf owning two rooms, or a household
  with no bedroom while free ones stand: the house_dwarves action, which keeps
  the better room for the couple, frees the other and gives the best free
  room each household with none can walk to (children ride on a parent's);
* more households without a bedroom than free bedrooms: a bedrooms level for
  the difference (the bed rule counts every bed, the hospital's and the
  barracks' too, so it can see enough beds while households have none);
* five or more citizens unhappy or worse and free bedrooms standing: up to
  ten of the most stressed moved to a free room much better for them, an
  item's value counted once more for each of their likes it matches (DF
  wiki, Preference), a week apart;
* citizens who slept rough lately (SleptGrass, SleptFloor...): a note saying
  whether they lack a room or sleep away from the one they have.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import Proposal, player_rules, PLANNER_CONFIG  # noqa: F401
from planner_building import room_size

__all__ = ["_homes_rules", "homes_census"]


def homes_census(s: dict) -> dict:
    """(0.104.168) The report's homes section ({} from an older bridge)."""
    return _d(s.get("homes"))


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _homes_rules(s: dict, cfg: dict, traits: dict, proposals: list, notes: list) -> None:
    """(0.104.168) Children's beds, couples' rooms, rooms the stressed like."""
    h = homes_census(s)
    if not h or "error" in h:
        return
    free = _int(h.get("free_bedrooms"))
    wanted = _int(h.get("rooms_wanted"))          # households (and children with no parent here) with no bedroom
    apart = _int(h.get("couples_apart")) + _int(h.get("couples_unlinked")) + _int(h.get("hoarders"))
    rough = _int(h.get("rough"))
    if rough >= cfg["homes_rough_note_at"]:
        housed = _int(h.get("rough_housed"))
        far = _int(h.get("rough_unreachable"))
        kids = _int(h.get("rough_children"))
        why = []
        if rough > housed:
            why.append(f"{rough - housed} with no bedroom")
        if housed:
            why.append(f"{housed} away from the bedroom they have"
                       + (f" ({far} can't walk to it)" if far else " (far from it when tired, or kept out by a burrow)"))
        notes.append(f"{rough} citizens slept rough in the last 28 days"
                     + (f" ({kids} of them children)" if kids else "") + ": " + ", ".join(why))
    # one room per household; a room for each household with none
    give = min(wanted, free)
    if apart or give:
        n = min(30, apart + give)
        bits = []
        if _int(h.get("couples_apart")):
            bits.append(f"{h['couples_apart']} married couple(s) in two rooms (DF's couples share one)")
        if _int(h.get("couples_unlinked")):
            bits.append(f"{h['couples_unlinked']} couple(s) whose room is in one spouse's name only")
        if _int(h.get("hoarders")):
            bits.append(f"{h['hoarders']} dwarf(s) owning two bedrooms")
        if give:
            kids = _int(h.get("children_roomless"))
            bits.append(f"{wanted} household(s) with no bedroom" + (f" ({kids} children without one)" if kids else "")
                        + f" and {free} free")
        proposals.append(Proposal("homes", {"type": "house_dwarves", "house": n},
                                  "; ".join(bits) + ": one bedroom per household, the better one kept", 4))
    # more households without a bedroom than free ones: dig the difference
    short = wanted - free
    open_kinds = {_d(p).get("kind") for p in _l(_d(s.get("projects")).get("open"))}
    digging = any(p.action.get("type") == "start_project" and p.action.get("kind") == "bedrooms" for p in proposals)
    if short > 0 and "bedrooms" not in open_kinds and not digging:
        rooms = min(32, short + cfg["min_spare_beds"])
        proposals.append(Proposal("homes_dig", {"type": "start_project", "kind": "bedrooms", "rooms": rooms,
                                                "room_size": room_size(traits)},
                                  f"{wanted} household(s) have no bedroom and {free} bedroom(s) are free "
                                  f"(the fort's other beds are the hospital's, the barracks' or outside a room): "
                                  f"dig {rooms} bedrooms", 4))
    # the stressed to rooms they like (their likes raise a room's worth to them)
    st = _d(_d(s.get("dwarves")).get("stress"))
    stressed = sum(_int(st.get(k)) for k in ("miserable", "very_unhappy", "unhappy"))
    if stressed >= cfg["homes_liked_min_stressed"] and free - give > 0:
        n = min(cfg["homes_liked_max"], free - give)
        proposals.append(Proposal("homes_liked", {"type": "house_dwarves", "house": 0, "upgrade": n},
                                  f"{stressed} citizens are unhappy or worse and {free} bedrooms are free: up to {n} "
                                  "of the most stressed move to a free room much better for them (furniture of "
                                  "a material or kind they like counts more)", 5))
