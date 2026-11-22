"""planner_garden (0.105.47): the Garden fort's gardens. The player (14 Nov):
"garden fort should have gardens". In the run the Garden fort (F) had the
most garden levels (9), statues and meeting halls, but its surface character
never showed: "halls and kitchens by the fields" read 0 and nothing stood by
its 12 surface fields.

- `_garden_court_rule`: the garden court above ground (lua/ai-builder-court.lua,
  `place_garden_court`, one stage a call): a walled court by the fields with
  beds (farm plots), the trees already inside, block paths, statues, seats
  and a meeting area. For high Agriculture + Grandeur + Surface (the Garden
  fort: 120, 40, 80), or a fort whose design language wishes one
  (design_rules: "for the fort's nature lovers") above a low Surface; never
  underground only nor the Hermit hold's hidden_hold. Quiet as every
  construction is (construct_quiet: the halt, the Rules tab's construction
  switch, a crisis, threats); one building above ground at a time (it waits
  for the keep and the surface hall).
- `garden_pace`: the statue gardens (planner_building's set piece) come
  sooner by Agriculture (good_times' pace).
- `court_wished`: the design language's garden_court wish, or a landmark
  handed over to the court (planner_design._fallback).

The field customs' surface case (dining and food shops under the surface
fields) is masterplan.hint's (fields.py).
"""

from __future__ import annotations

import re

import customs
import masterplan
from digest import _d, _l
from planner_core import Proposal, free_stock, young_fort

__all__ = ["court_wanted", "court_wished", "court_opts", "garden_pace", "court_status", "_garden_court_rule",
           "COURT_STAGE_WORDS"]

COURT_STAGE_WORDS = {
    None: "a walled garden court by the fields: beds, paths, statues and seats",
    "clearing": "the garden court: the trees on its walls' line are down, raise the walls and the door",
    "walls": "the garden court: its walls stand, lay its beds and paths",
    "beds": "the garden court: its beds are laid, set its statues and seats",
    "furnish": "the garden court: furnished, make it a meeting place",
}
NAME_RE = re.compile(r"^[A-Za-z' ]{1,40}$")


def _v(traits: dict | None, k: str) -> float:
    try:
        return float(_d(traits).get(k, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def garden_pace(traits: dict | None, cfg: dict) -> float:
    """(0.105.47) How much sooner the statue gardens come: x2 ** (Agriculture /
    garden_agri_pace_div) for Agriculture above 0 (120: x1.74), else x1."""
    if not cfg.get("garden_fort", True):
        return 1.0
    a = max(0.0, _v(traits, "agriculture"))
    return 2 ** (a / max(1.0, float(cfg.get("garden_agri_pace_div", 150))))


def court_wished(memory) -> bool:
    """The design language wishes a garden court (its landmarks), or a
    garden_court landmark was handed to the court (planner_design)."""
    try:
        import design
        lang = design.current(getattr(memory, "culture", None)) if memory is not None else None
    except Exception:  # noqa: BLE001
        lang = None
    if any(_d(w).get("kind") == "garden_court" for w in _l(_d(lang).get("landmarks"))):
        return True
    lm = _d(_d(getattr(memory, "atlas", None)).get("landmarks"))
    return any(_d(e).get("kind") == "garden_court" and _d(e).get("status") == "court" for e in _l(lm.get("list")))


def court_wanted(traits: dict | None, cfg: dict, memory=None) -> str | None:
    """Why the fort raises a garden court, or None. Never under the ground
    only (Surface -80 or lower) nor with hidden_hold."""
    traits = _d(traits)
    if masterplan.underground_only(traits) or customs.has(traits, "hidden_hold"):
        return None
    a, g, su = _v(traits, "agriculture"), _v(traits, "grandeur"), _v(traits, "surface")
    if (a >= cfg["garden_court_agriculture"] and g >= cfg["garden_court_grandeur"]
            and su >= cfg["garden_court_surface"]):
        return f"Agriculture {a:+.0f}, Grandeur {g:+.0f} and Surface {su:+.0f}"
    if su > cfg["garden_court_wish_surface"] and court_wished(memory):
        return "the fort's design wishes a garden court (for its nature lovers)"
    return None


def court_status(s: dict) -> dict | None:
    st = s.get("garden_court")
    return st if isinstance(st, dict) and st.get("stage") else None


def _court_name(s: dict, memory) -> str:
    """A plain name for the court's meeting area: the fort's next garden
    name (planner_building.garden_name), else "Green"."""
    try:
        from planner_building import garden_name
        n = garden_name(s, memory) if memory is not None else None
    except Exception:  # noqa: BLE001
        n = None
    return n if isinstance(n, str) and NAME_RE.match(n) else "Green"


def court_opts(s: dict, traits: dict, cfg: dict, memory=None) -> dict:
    """What the sliders give the court: block paths with Grandeur
    garden_court_paths_grandeur+, statues by Grandeur (2, or 4 at 40+; only
    free ones are placed), its name."""
    g = _v(traits, "grandeur")
    return {"name": _court_name(s, memory), "paths": g >= cfg["garden_court_paths_grandeur"],
            "statues": 4 if g >= 40 else 2 if g >= 0 else 0}


def _waiting(st: dict) -> str | None:
    stage = st.get("stage")
    if stage == "clearing" and int(st.get("trees_left") or 0) > 0:
        return f"the garden court: the woodcutters fell {st['trees_left']} tree(s) on its walls' line"
    if stage == "walls" and int(st.get("walls_planned") or 0) > 0:
        return f"the garden court: {st['walls_planned']} wall tile(s) still to build"
    # (r9, audit A3 12) a chair or a statue that never comes holds the court
    # COURT_WAIT_DAYS at most: past it (wait_over), or with no start known (an
    # older save: the call records it), the next step is asked anyway
    if (stage in ("beds", "furnish") and int(st.get("planned") or 0) > 0
            and st.get("stage_days") is not None and not st.get("wait_over")):
        return f"the garden court: {st['planned']} piece(s) still to build ({stage})"
    return None


def _garden_court_rule(s: dict, cfg: dict, citizens: int, traits: dict, proposals: list, notes: list,
                       memory=None, rules_: dict | None = None) -> None:
    """(0.105.47) The garden court, one stage a call (see the module)."""
    if not cfg.get("garden_fort", True):
        return
    why = court_wanted(traits, cfg, memory)
    if not why:
        return
    st = court_status(s)
    if st and (st.get("done") or st.get("stage") == "done"):
        return
    from planner_construct import construct_quiet, hall_open, keep_open
    quiet = construct_quiet(s, memory, traits, cfg, rules_)
    if quiet:
        return
    if st:
        w = _waiting(st)
        if w:
            notes.append(w)
            return
    if young_fort(s, cfg) or citizens < cfg["garden_court_min_citizens"]:
        return
    if not st:
        busy = keep_open(s) or hall_open(s)
        if busy:
            notes.append(f"the garden court waits for the keep or the surface hall ({busy}): one building above "
                         "ground at a time")
            return
        stocks = _d(s.get("stocks"))
        have = free_stock(s, "blocks") + int(stocks.get("boulders") or 0) + int(stocks.get("wood") or 0)
        if have < cfg["garden_court_material"]:
            notes.append(f"the garden court waits for building material ({have} blocks, stone and logs free; "
                         f"its walls want {cfg['garden_court_material']})")
            return
    stage = st.get("stage") if st else None
    words = COURT_STAGE_WORDS.get(stage, "the garden court: its next step")
    if not st:
        words = f"{why}: {words}"
    proposals.append(Proposal("garden_court", {"type": "place_garden_court", **court_opts(s, traits, cfg, memory)},
                              words, 7))
