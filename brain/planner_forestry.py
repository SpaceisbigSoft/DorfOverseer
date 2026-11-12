"""(item10) Wood that lasts: cavern trees logged when safe, and a grove kept.

The `forestry` report (lua/ai-forestry.lua): the revealed trees and saplings
by where they stand (surface, cavern, inside: the fort's own underground
soil), the cavern and inside trees the dwarves can reach, those marked for
felling (`ai_marked`: by the AI and still standing), the cavern layers (z
bands, `danger`: a danger on a cavern tile near it), the cavern dangers, and
the AI's grove.

Cavern logging (`cavern_logging`, Rules switch "cavern_logging", on by
default) when all of these hold:

  * wood is short (fewer logs than `wood_per_dwarf` a citizen) and the
    surface has few trees left to fell (`cavern_logging_surface_min`, the
    grove's not counted), or autochop is held off by the elves' quota;
  * the caverns are watched: every opening onto them the AI knows (the
    threats report's `openings`) has a built door or hatch the gate watcher
    can shut, at least one is known, and no seal is in place (a great beast);
  * the layer has no danger near it (the bridge leaves those trees out too,
    and none within 25 tiles of any danger);
  * the elves' quota has room: the DF wiki (Elf) says fungus "trees" count
    toward it as well, so cavern logging stops where surface felling stops
    (`tree_quota_share` of the cap), and marks no more than the room left.

`cavern_logging_stop` (stop: true): the AI's marks still standing are lifted
while a danger is near a cavern layer, a seal is up, the switch is off, or
an opening stands without a door.

The grove (`keep_grove`): once the fort has `grove_min_saplings` saplings on
the surface, a patch near the fort with the most of them is kept (restricted
traffic; its trees' felling marks lifted). Each day after, while wood is not
in crisis (`grove_release_wood` logs or more), autochop's marks in it are
lifted (guard). In a crisis the grove is left to the woodcutters (said).
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import AGENDA_THEMES, Proposal, player_rules
from planner_labor import trees_this_year

__all__ = ["_cavern_logging_rule", "_grove_rule", "caverns_watched", "forestry_line"]

AGENDA_THEMES.update({"cavern_logging": "fell cavern trees for wood", "cavern_logging_stop": "call the woodcutters back",
                      "grove": "keep a grove of young trees"})


def caverns_watched(s: dict) -> tuple[bool, str]:
    """Every known opening onto the caverns has a built door or hatch, and no
    seal is up. (ok, why not)."""
    th = _d(s.get("threats"))
    if "error" in th or not th:
        return False, "no threats report"
    if any(isinstance(v, dict) for v in _d(th.get("sealed")).values()):
        return False, "the caverns are sealed against a great beast"
    ops = [o for o in _l(_d(th.get("openings")).get("list")) if isinstance(o, dict)]
    if not ops:
        return False, "no known way into the caverns"
    bare = [o for o in ops if o.get("building") not in ("Door", "Hatch") or o.get("built") is False]
    if bare:
        return False, f"{len(bare)} way(s) into the caverns without a door or hatch"
    return True, ""


def _wood_short(s: dict, cfg: dict, citizens: int) -> tuple[bool, int]:
    wood = int(_d(s.get("stocks")).get("wood") or 0)
    return wood < max(1, citizens) * cfg["wood_per_dwarf"], wood


def _cavern_logging_rule(s: dict, memory, cfg: dict, citizens: int, proposals: list, notes: list) -> None:
    f = _d(s.get("forestry"))
    if not f or "error" in f:
        return
    rules_ = player_rules(s)
    watched, why = caverns_watched(s)
    layers = [l for l in _l(f.get("layers")) if isinstance(l, dict)]
    danger = any(l.get("danger") for l in layers) or int(f.get("cavern_dangers") or 0) > 0
    ai_marked = int(f.get("ai_marked") or 0)
    if ai_marked > 0 and (danger or not watched or not rules_["cavern_logging"]):
        reason = ("a danger is in the caverns" if danger else why if not watched
                  else "cavern logging is switched off")
        proposals.append(Proposal("cavern_logging_stop", {"type": "cavern_logging", "stop": True},
                                  f"{ai_marked} cavern tree(s) marked for felling and {reason}: "
                                  "unmark them (the woodcutters stay out)", 2))
        return
    if not rules_["cavern_logging"]:
        return
    short, wood = _wood_short(s, cfg, citizens)
    if not short:
        return
    felled, cap = trees_this_year(s, memory)
    room = None
    if cap:
        room = int(cap * cfg["tree_quota_share"]) - felled
        if room <= 0:
            notes.append(f"wood is short ({wood}) and the elves' quota is near ({felled} of {cap} felled): "
                         "cavern trees count toward it too (DF wiki), so none are felled until the new year")
            return
    cave, inside = _d(f.get("cavern")), _d(f.get("inside"))
    grove_trees = int(_d(f.get("grove")).get("trees") or 0)
    surface_left = int(_d(f.get("surface")).get("trees") or 0) - grove_trees
    if surface_left >= cfg["cavern_logging_surface_min"]:
        return
    reach = int(cave.get("reachable") or 0) + int(inside.get("reachable") or 0)
    if reach <= 0:
        if int(cave.get("trees") or 0) > 0:
            notes.append(f"wood is short ({wood}) and {cave.get('trees')} cavern tree(s) stand where the "
                         "woodcutters can't reach")
        return
    inside_only = False
    if int(cave.get("reachable") or 0) > 0 and not watched:
        notes.append(f"wood is short ({wood}) and cavern trees stand within reach, but {why}: "
                     "no woodcutter goes down")
        if int(inside.get("reachable") or 0) <= 0:
            return
        inside_only, reach = True, int(inside.get("reachable") or 0)
    if danger:
        notes.append("wood is short, but a danger is in the caverns: the woodcutters fell none there "
                     "(only trees inside the fort, if any)")
    want = cfg["cavern_logging_batch"] - ai_marked
    if room is not None:
        want = min(want, room)
    want = min(want, reach)
    if want <= 0:
        return
    action = {"type": "cavern_logging", "limit": want}
    if inside_only:
        action["inside_only"] = True
    proposals.append(Proposal("cavern_logging", action,
                              f"wood is short ({wood} logs for {citizens} dwarves) and {max(0, surface_left)} "
                              f"tree(s) left on the surface: fell {want} "
                              + ("underground tree(s) inside the fort" if inside_only else
                                 f"cavern tree(s) ({reach} within reach, the caverns' ways in watched)"), 5))


def _grove_rule(s: dict, cfg: dict, citizens: int, proposals: list, notes: list) -> None:
    f = _d(s.get("forestry"))
    if not f or "error" in f:
        return
    g = _d(f.get("grove"))
    short, wood = _wood_short(s, cfg, citizens)
    if not g:
        sap = int(_d(f.get("surface")).get("saplings") or 0)
        if sap >= cfg["grove_min_saplings"]:
            proposals.append(Proposal("grove", {"type": "keep_grove"},
                                      f"{sap} saplings on the surface: keep a grove near the fort (restricted "
                                      "traffic, no felling) so the wood grows back over the years", 6))
        return
    if int(g.get("marked") or 0) <= 0:
        return
    if wood < cfg["grove_release_wood"]:
        notes.append(f"only {wood} logs: the grove's {g.get('marked')} marked tree(s) are left to the woodcutters")
        return
    proposals.append(Proposal("grove", {"type": "keep_grove", "guard": True},
                              f"{g.get('marked')} tree(s) in the AI's grove marked for felling: unmark them "
                              "(the grove grows the fort's wood for later years)", 6))


def forestry_line(s: dict) -> str:
    """The forestry in one line; "" without the section."""
    f = _d(s.get("forestry"))
    if not f or "error" in f:
        return ""
    sur, cave = _d(f.get("surface")), _d(f.get("cavern"))
    bits = [f"trees: {sur.get('trees', 0)} surface ({sur.get('saplings', 0)} saplings), "
            f"{cave.get('trees', 0)} cavern ({cave.get('reachable', 0)} in reach)"]
    if f.get("ai_marked"):
        bits.append(f"{f['ai_marked']} marked by the AI")
    g = _d(f.get("grove"))
    if g:
        bits.append(f"grove {g.get('trees', 0)} trees, {g.get('saplings', 0)} saplings")
    return "; ".join(bits)
