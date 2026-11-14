"""(0.105.47) The deep plan's descent: the main stair past the first cavern,
and the deep districts' levels under it as the fort grows (Verticality).

Why (the 14 Nov scorecard): Verticality's lines went to the wrong fort.
Height span A 20, B 30, C 20, D 12, E 17, F 24; deepest level below the
surface A 19, B 29, C 19, D 11, E 8, F 23: the Deep mine (E, Verticality
120) was the shallowest. The master plan keeps every district
CAVERN_MARGIN levels over the first cavern (masterplan._range) and the
builder's stair never enters a cavern tile (lua/ai-builder-sites.lua
check_extension), so a deep plan could never get past Cavern1 (0.105.44
G6: "deeper needs a stair past Cavern1 (open item)").

  * the crossing (`cross_cavern`, lua/ai-descent.lua): at Verticality
    masterplan.CROSS_VERTICALITY (100) or more, once the fort has
    `descent_min_citizens` and `descent_min_levels` levels in its plan, the
    spine is taken down through the first cavern in a walled shaft, a step
    at a time (the rock above, each cavern level, the rock below). The
    bridge refuses water, magma, aquifers, warm stone, the dig guard's
    tiles and the lowest cavern; a step waits while the last one is being
    dug or built, a hostile creature is in the layer near the stair, or the
    caverns are sealed against a great beast. Nothing is proposed while a
    threat can reach the dwarves.
  * the deep levels (deep_pass, after every rule): once the crossing stands
    (the `descent` section says built), every new level of a deep district
    goes to masterplan.deep_band under it: the industry from the start, the
    storage once the fort has `descent_storage_citizens`, the homes too at
    Verticality `descent_homes_verticality` and `descent_homes_citizens`.

Without a `descent` section (an older bridge, the fixtures) nothing here
proposes or changes anything.
"""

from __future__ import annotations

import masterplan
from digest import _d, _l, game_text
from planner_core import Proposal, _traits, young_fort

__all__ = ["descent", "deep_kinds", "_descent_rule", "deep_pass"]


def descent(s: dict) -> dict | None:
    """The report's `descent` section; None when there is none (or it failed)."""
    d = s.get("descent")
    if not isinstance(d, dict) or not d or "error" in d:
        return None
    return d


def deep_kinds(traits: dict, citizens: int, cfg: dict) -> set[str]:
    """The plan's districts whose new levels go under the crossing."""
    out = {"industry"}
    if citizens >= cfg["descent_storage_citizens"]:
        out.add("storage")
    if (traits.get("verticality", 0) or 0) >= cfg["descent_homes_verticality"] and citizens >= cfg["descent_homes_citizens"]:
        out.add("homes")
    return out


def _plan_levels(memory) -> int:
    p = masterplan._peek(memory)
    return sum(len(_l(d.get("levels"))) for d in _l(p.get("districts")) if isinstance(d, dict))


def _descent_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """The next step of the crossing, when the fort is deep-minded and grown."""
    d = descent(s)
    traits = _traits(s)
    if d is None or memory is None or not masterplan.crosses_caverns(traits) or not cfg.get("deep_descent", True):
        return
    state = d.get("state")
    if state == "blocked":
        notes.append(f"the stair can't be taken past {d.get('layer') or 'the cavern'}: "
                     f"{game_text(d.get('why'), 120)}; the deep levels stay over it")
        return
    if state in ("built", "working"):
        return
    if d.get("danger"):
        notes.append(f"the stair through {d.get('layer')} waits: {d['danger']} hostile creature(s) in the cavern "
                     "near it")
        return
    if d.get("sealed"):
        notes.append(f"the stair through {d.get('layer')} waits: the caverns are sealed against a great beast")
        return
    cav = masterplan.cavern_to_cross(memory)
    spine = _d(masterplan._peek(memory).get("spine"))
    if not cav or not isinstance(spine.get("x"), int) or not isinstance(spine.get("bottom"), int):
        return
    if state == "none":
        citizens = int(_d(s.get("dwarves")).get("total") or 0)
        if young_fort(s, cfg) or citizens < cfg["descent_min_citizens"]:
            return
        if _plan_levels(memory) < cfg["descent_min_levels"]:
            return
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return
    step = ("begin the stair down" if state == "none" else
            f"the next step of the stair ({d.get('steps_done', 0)} of {d.get('steps', '?')} done)")
    proposals.append(Proposal(
        "deep_descent", {"type": "cross_cavern", "x": spine["x"], "y": spine["y"],
                         "elev": int(spine["bottom"]), "layer": cav["name"]},
        f"Verticality {traits.get('verticality', 0)}: the fort goes deeper than {cav['name']} "
        f"(elevations {cav['bottom']} to {cav['top']}): {step} through it in a walled shaft, "
        "so new levels can go under it", 6))


def deep_pass(proposals: list, s: dict, memory, cfg: dict, citizens: int) -> None:
    """Every new level of a deep district sent under the crossing once it stands."""
    d = descent(s)
    traits = _traits(s)
    if (d is None or d.get("state") != "built" or memory is None or not masterplan.crosses_caverns(traits)
            or not cfg.get("deep_descent", True)):
        return
    bottom = d.get("elevation_bottom")
    if not isinstance(bottom, int) or isinstance(bottom, bool):
        return
    cav = masterplan.cavern_to_cross(memory) or {}
    kinds = deep_kinds(traits, citizens, cfg)
    for p in proposals:
        a = p.action
        if not isinstance(a, dict) or a.get("type") != "start_project" or a.get("urgent"):
            continue
        if masterplan.DISTRICT_OF.get(a.get("kind")) not in kinds or a.get("set_piece"):
            continue
        band = masterplan.deep_band(memory, a["kind"], bottom, cav.get("next_top"), cfg["descent_band_levels"])
        if not band:
            continue
        where = dict(a["plan"]) if isinstance(a.get("plan"), dict) else {}
        where.update(band)
        a["plan"] = where
        p.reason += f" (under {d.get('layer') or 'the cavern'}, elevations {band['elev_lo']} to {band['elev_hi']})"
