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

(E4, the Design track's personal rooms) At Design Guided or Architect, with
the report's `citizens_taste` section (lua/ai-homes.lua citizens_taste: each
grown-up's personality, dreams and likes, summed):

* the house_dwarves moves carry `place`: each room is chosen by its place
  too (an artist by their craft's workshop, family near the families,
  rulers and warriors near the great halls, nature lovers near the fields,
  the quiet away from the busy halls, the gregarious near the tavern), and
  no one is moved out of a room they like;
* rooms the AI dug whose owner would like a piece the stock has (a statue
  showing a creature they like, furniture of a material they like): the
  furnish_liked action, a week apart, never while a strange mood gathers.

At Scripts, or with no such section, nothing here changes.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import Proposal, player_rules, PLANNER_CONFIG  # noqa: F401
from planner_building import room_size

__all__ = ["_homes_rules", "homes_census", "citizens_taste", "taste_on"]


def homes_census(s: dict) -> dict:
    """(0.104.168) The report's homes section ({} from an older bridge)."""
    return _d(s.get("homes"))


def citizens_taste(s: dict) -> dict:
    """(E4) The report's citizens_taste section ({} from an older bridge or on error)."""
    t = _d(s.get("citizens_taste"))
    return {} if "error" in t or "citizens_taste" in _d(s.get("_errors")) else t


def taste_on(s: dict) -> bool:
    """(E4) The citizens' taste places and furnishes rooms: Design Guided or
    Architect, and the taste was read."""
    try:
        from planner_design import mode_of
        mode = mode_of(s)
    except Exception:  # noqa: BLE001
        mode = "scripts"
    return mode in ("guided", "architect") and _int(citizens_taste(s).get("adults")) > 0


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
    # one room per household; a room for each household with none that can
    # walk to a free one ((0.104.168, review) the action gives only those: an
    # unreachable one counted here was proposed and refused every day)
    reach = _int(h.get("rooms_reachable")) if "rooms_reachable" in h else wanted
    give = min(reach, free)
    if wanted > reach and free:
        notes.append(f"{wanted - reach} household(s) with no bedroom can't walk to any of the {free} free ones "
                     "(cut off, or outside the fort)")
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
            bits.append(f"{reach} household(s) with no bedroom" + (f" ({kids} children without one)" if kids else "")
                        + f" and {free} free")
        act = {"type": "house_dwarves", "house": n}
        why = "; ".join(bits) + ": one bedroom per household, the better one kept"
        if taste_on(s):
            act["place"] = True
            why += ", each new room placed by its dwarf's taste"
        proposals.append(Proposal("homes", act, why, 4))
    # more households without a bedroom than free ones: dig the difference
    short = wanted - free
    open_kinds = {_d(p).get("kind") for p in _l(_d(s.get("projects")).get("open"))}
    digging = any(p.action.get("type") == "start_project" and p.action.get("kind") == "bedrooms" for p in proposals)
    # ((0.104.168, review) not when the projects section failed: an open
    # bedrooms level would go unseen and a second one start)
    projects_ok = "projects" not in _d(s.get("_errors")) and "error" not in _d(s.get("projects"))
    if short > 0 and projects_ok and "bedrooms" not in open_kinds and not digging:
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
        act = {"type": "house_dwarves", "house": 0, "upgrade": n}
        why = (f"{stressed} citizens are unhappy or worse and {free} bedrooms are free: up to {n} "
               "of the most stressed move to a free room much better for them (furniture of "
               "a material or kind they like counts more)")
        if taste_on(s):
            act["place"] = True
            why += ", and in a place that suits them (never out of a room they like)"
        proposals.append(Proposal("homes_liked", act, why, 5))
    _furnish_rule(s, cfg, proposals)


PLACE_WORDS = {"artist": "artists", "family": "family-minded", "imposing": "rulers and warriors",
               "nature": "nature lovers", "quiet": "quiet ones", "social": "gregarious"}


def _furnish_rule(s: dict, cfg: dict, proposals: list) -> None:
    """(E4) A piece of the stock's furniture each citizen would like, in their own room."""
    if not taste_on(s):
        return
    t = citizens_taste(s)
    ready = _int(t.get("furnish_ready"))
    if ready <= 0 or t.get("strange_mood"):
        return
    n = min(int(cfg.get("homes_furnish_max", 5)), ready)
    place = _d(t.get("place"))
    who = ", ".join(f"{_int(v)} {PLACE_WORDS.get(k, k)}" for k, v in sorted(place.items(), key=lambda kv: (-_int(kv[1]), kv[0]))
                    if _int(v) > 0)[:120]
    proposals.append(Proposal("homes_furnish", {"type": "furnish_liked", "n": n},
                              f"{ready} citizen(s) own a room the AI dug that lacks a piece they would like and "
                              f"the stock has one (a statue showing a creature they like, furniture of a material "
                              f"they like): up to {n} put up" + (f" (the fort: {who})" if who else ""), 6))
