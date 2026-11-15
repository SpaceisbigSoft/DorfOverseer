"""floor_grammar: a fort's sliders, a level's style, the master plan's layout
pattern and the fort's quirks and customs into the floor grammar of a
hallway-first level (layout B): how far apart rooms sit, how long a hall runs
before it turns, how many halls leave the stair, whether rooms face each
other, where the hall widens. masterplan_floors.hint calls grammar() and adds
the rest of the hint (which floors, which district); the bridge's parse_floor
checks the result against ai-floorplan's ranges (RANGES here, the same
numbers).

Pure: no memory, no bridge, nothing of the planner but PLANNER_CONFIG as the
default cfg. Spacing and Room size are separate sliders: Spacing moves the
gaps, the lead and the sides; Room size the pile rooms and the run. Depth
(`verticality`) moves the run and the arms."""

from __future__ import annotations

import hashlib
import math

from planner_config import PLANNER_CONFIG

__all__ = ["grammar", "KEYS", "RANGES", "DEFAULTS", "STAGGERS"]

# every key of the result, in the hint's order
KEYS = ("gap", "kind_gap", "lead", "ahead", "run_max", "run_min", "arms_max", "sides", "stagger", "bay",
        "node", "grow", "turns", "balance", "axial", "neck", "pile_w", "piles_new", "full_retry_days")

# the bridge's ranges for the whole numbers (lua/ai-floorplan.lua G; parse_floor for pile_w, piles_new)
RANGES = {"gap": (1, 4), "kind_gap": (0, 6), "lead": (0, 8), "ahead": (0, 3), "run_max": (12, 80),
          "run_min": (4, 30), "arms_max": (1, 4), "stagger": (0, 6), "pile_w": (3, 11), "piles_new": (0, 3),
          "full_retry_days": (1, 336)}

# the config block's defaults (brain/planner_config.py, the last block): every read is cfg.get(key, this)
DEFAULTS = {
    "floor_gap": 1, "floor_gap_wide": 50, "floor_gap_far": 100, "floor_tight_spacing": -50,
    "floor_kind_gap": 1, "floor_lead": 2,
    "floor_run": 30, "floor_run_deep": 20, "floor_run_very_deep": 14, "floor_run_flat": 44,
    "floor_run_very_flat": 60, "floor_run_dogleg": 0.6, "floor_run_aspect": 1.25, "floor_run_min": 10,
    "floor_run_room": 0.15,
    "floor_arms_deep": 1, "floor_arms": 2, "floor_arms_flat": 4,
    "floor_node_grandeur": 60, "floor_axial_grandeur": 40,
    "floor_pile_small": 5, "floor_pile": 5, "floor_pile_large": 7,
    "floor_piles_new": 1, "floor_piles_stock": 50,
    "floor_elevs_max": 4, "floor_full_retry_days": 28, "floor_note_days": 3,
}

STAGGERS = (0, 2, 3)                 # columns the +1 side's first slot is shifted by, picked by the fort's seed
ONE_SIDE_SPACING = 150               # Spacing at or past this: rooms on one side of a hall only
DOGLEG_FORTIFICATION = 50            # as masterplan._grammar: the corridors are dog-leg
FORTIFIED_FORTIFICATION = 70         # as masterplan._grammar: the doors are fortified
WIDE_SCALE = 130                     # style scale at or past this: a 5x5 square where a hall turns
DEPTH_STEP, DEPTH_FAR = 40, 100      # Depth's two bars each way (the config table's "40+", "100+")
SIZE_STEP = 50                       # one Room size step
GROW = {"grid": (["arm", "turn"], "alternate"), "rings": (["turn", "arm"], "right"),
        "branching": (["turn", "arm"], "both"), "stacked": (["arm"], "alternate")}


BIG = 10 ** 9                         # no slider or tuning number is past this (keeps the sums finite)


def _num(v, default=0):
    """A finite number (held inside +-BIG), else the default (junk, a bool, NaN, an endless number)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    if isinstance(v, float) and not math.isfinite(v):
        return default
    return max(-BIG, min(BIG, v))


def _clamp(v, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def _round(v) -> int:
    """Half up (34.5 -> 35, whatever the float's last bit says)."""
    return int(math.floor(v + 0.5 + 1e-9))


def _names(v) -> frozenset:
    """The quirks / customs as a set of names; junk is no names."""
    if isinstance(v, str):
        return frozenset((v,))
    try:
        return frozenset(x for x in v if isinstance(x, str))
    except TypeError:
        return frozenset()


def grammar(traits: dict, style: dict | None, cfg: dict | None = None, *, pattern: str = "grid",
            quirks: frozenset = frozenset(), customs: frozenset = frozenset(), doors: str | None = None,
            seed: str = "fort", language: bool = False, grand: bool = False, urgent: bool = False) -> dict:
    """The hint's grammar keys (KEYS), every one inside the bridge's ranges.

    traits: the sliders (spacing, size, verticality, grandeur, fortification, stockpile); style: the level's
    style (aspect, arms, symmetry, scale, rhythm, grand); pattern: the master plan's layout pattern; quirks:
    the earned rules that bend it (narrow_ways, great_shaft, symmetric); customs: the active customs' ids
    (winding_ways); doors: the plan's "open" | "doored" | "fortified" (None: by Fortification, as the plan
    would say); seed: the fort's culture seed; language: the fort follows a design language (the style's
    rhythm then counts); grand: the level is a set piece; urgent: nothing is dug ahead. Never raises: junk
    reads as 0 / the default."""
    traits = traits if isinstance(traits, dict) else {}
    style = style if isinstance(style, dict) else {}
    cfg = PLANNER_CONFIG if cfg is None else (cfg if isinstance(cfg, dict) else {})
    quirks, customs = _names(quirks), _names(customs)

    def c(key):
        return _num(cfg.get(key, DEFAULTS[key]), DEFAULTS[key])

    def t(name):
        return _num(traits.get(name, 0) or 0)

    spacing, size, depth = t("spacing"), t("size"), t("verticality")
    grandeur, fort, stock = t("grandeur"), t("fortification"), t("stockpile")
    symmetry, arms = style.get("symmetry"), style.get("arms")
    symmetry = symmetry if isinstance(symmetry, str) else None
    arms = arms if isinstance(arms, str) else None
    mirror = symmetry == "mirror" or "symmetric" in quirks          # Mirror-minded
    radial = symmetry == "radial"
    cross = arms == "cross"
    warren = "narrow_ways" in quirks

    # Spacing: the gaps, the lead, the sides (and nothing of the rooms' size)
    steps = (1 if spacing >= c("floor_gap_wide") else 0) + (1 if spacing >= c("floor_gap_far") else 0)
    tight = spacing <= c("floor_tight_spacing")
    out = {"gap": _clamp(c("floor_gap") + steps, *RANGES["gap"]),
           "kind_gap": 0 if tight else _clamp(c("floor_kind_gap") + 2 * steps, *RANGES["kind_gap"]),
           "lead": 0 if tight else _clamp(c("floor_lead") + 2 * steps, *RANGES["lead"]),
           "ahead": 0 if (urgent or tight) else 1}

    # the run: by Depth, shorter for a dog-leg fort, by the language's aspect, by Room size
    if depth <= -DEPTH_FAR:
        run = c("floor_run_very_flat")
    elif depth <= -DEPTH_STEP:
        run = c("floor_run_flat")
    elif depth >= DEPTH_FAR:
        run = c("floor_run_very_deep")
    elif depth >= DEPTH_STEP:
        run = c("floor_run_deep")
    else:
        run = c("floor_run")
    if fort >= DOGLEG_FORTIFICATION or warren:
        run *= c("floor_run_dogleg")
    aspect = c("floor_run_aspect")
    if style.get("aspect") == "long":
        run *= aspect
    elif style.get("aspect") == "wide" and aspect > 0:
        run /= aspect
    size_steps = ((1 if size >= SIZE_STEP else 0) + (1 if size >= 2 * SIZE_STEP else 0)
                  - (1 if size <= -SIZE_STEP else 0) - (1 if size <= -2 * SIZE_STEP else 0))
    run *= 1 + c("floor_run_room") * size_steps
    lo, hi = RANGES["run_max"]
    out["run_max"] = _clamp(_round(max(lo, min(hi, run))), lo, hi)
    out["run_min"] = min(_clamp(c("floor_run_min"), *RANGES["run_min"]), out["run_max"])

    # the arms out of the stair: by Depth, then the symmetry, then the Great Shaft
    n = c("floor_arms_deep") if depth >= DEPTH_STEP else (c("floor_arms_flat") if depth <= -DEPTH_STEP
                                                         else c("floor_arms"))
    n = _clamp(n, *RANGES["arms_max"])
    if mirror:
        n = max(n, 2)
    if radial or cross:
        n = 4
    if "great_shaft" in quirks:
        n = 1
    out["arms_max"] = n

    out["sides"] = ("alternate" if warren or "winding_ways" in customs
                    else "one" if spacing >= ONE_SIDE_SPACING else "both")
    if mirror or radial:
        out["stagger"] = 0
    else:
        h = hashlib.sha1((str(seed) + "|stagger").encode("utf-8", "replace")).hexdigest()
        out["stagger"] = STAGGERS[int(h[:8], 16) % 3]
    rhythm = style.get("rhythm")
    out["bay"] = rhythm if (language and isinstance(rhythm, int) and not isinstance(rhythm, bool)
                            and 3 <= rhythm <= 6) else 0
    # Grandeur (or a big style) widens the turns; Spacing does not: the two sliders stay separate
    out["node"] = 5 if (grandeur >= c("floor_node_grandeur") or _num(style.get("scale"), 100) >= WIDE_SCALE) else 3

    how = "rings" if arms == "ring" else "grid" if cross else (pattern if isinstance(pattern, str) else "grid")
    grow, turns = GROW.get(how, GROW["grid"])
    out["grow"], out["turns"] = list(grow), turns
    out["balance"] = bool(mirror or radial or cross)
    out["axial"] = bool((grand or style.get("grand") is True) and grandeur >= c("floor_axial_grandeur"))
    out["neck"] = (doors == "fortified") if isinstance(doors, str) else fort >= FORTIFIED_FORTIFICATION

    out["pile_w"] = _clamp(c("floor_pile_small") if size <= -SIZE_STEP else c("floor_pile_large")
                           if size >= SIZE_STEP else c("floor_pile"), *RANGES["pile_w"])
    out["piles_new"] = _clamp(c("floor_piles_new") + (1 if stock >= c("floor_piles_stock") else 0),
                              *RANGES["piles_new"])
    out["full_retry_days"] = _clamp(c("floor_full_retry_days"), *RANGES["full_retry_days"])
    return {k: out[k] for k in KEYS}
