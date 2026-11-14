"""(0.105.47) The Stockpile slider's signature: a fort that keeps reserves.

Why (the 14 Nov scorecard): Stockpile won none of its lines (stockpiles A 60,
B 48, C 57, D 48, E 81, F 48; drink and meals a dwarf A 67.9, B 173.5, C 32.8,
D 130, E 127.9, F 129.7; Hermit hold +60 and Merchant city +40 should win).
What the slider did: one multiplier, 2^(Stockpile/100), on the drink, meals,
wood and blocks targets (x1.52 at +60): the stocks of every fort ran far
over those targets anyway (B's 4,427 servings for 28 dwarves were the
stores of a fort of 100), and nothing else in the fort followed it: the
storage levels, their size and the reserves of bars, blocks and cloth were
the same at -100 as at +100.

Now:
  * stock_factor(traits): 2^(Stockpile/50), 0.25 to 4 (x2.3 at +60, x1.74
    at +40, x0.5 at -50): the per-dwarf targets of drink, meals, wood and
    blocks (planner.py's `buffer`).
  * reserve_cfg(cfg, traits): the reserves kept follow it: cloth on hand
    (cloth_min, cloth_per_dwarf), bars kept back from furniture and
    precious crafts, and (never under their own number: the moods need
    them) the moods' reserves of cloth, bars, blocks, leather and logs.
  * the storage district (_reserve_storage_rule): at Stockpile
    `reserve_storage_min` or more, storage levels for the reserves (two
    food piles, bars and blocks, cloth, wood, furniture) until the fort has
    one for every `reserve_vault_citizens` / (factor - 1) citizens, a
    storage level at most every storage_gap_days / factor days; placed in
    the plan's storage district.
  * storage_room_size(traits): every storage level's piles 9x9 at +40, 11x11
    at +100, 7x7 between, 5x5 at -40 or lower (reserves_pass: on every
    storage level the rules propose; the Warren's and Waste Not's small
    storage keep their 5x5).
  * lean (Stockpile -40 or lower): the targets halve or less, small storage,
    no reserve levels.
"""

from __future__ import annotations

import math

import masterplan
from digest import _d
from planner_core import Proposal, TICKS_PER_DAY, abs_tick, young_fort

__all__ = ["stock_factor", "reserve_cfg", "storage_room_size", "reserve_storage_want", "storage_levels",
           "_reserve_storage_rule", "reserves_pass", "RESERVE_PILES"]

RESERVE_PILES = ["food", "food", "bars_blocks", "cloth", "wood", "furniture"]
# cfg keys scaled with the stock factor both ways, and those never under their own number
SCALED = ("cloth_min", "cloth_per_dwarf", "metal_furniture_bars", "precious_crafts_bars")
SCALED_UP = ("reserve_plant_cloth", "reserve_animal_cloth", "reserve_leather", "reserve_bars",
             "reserve_blocks", "reserve_logs")
LIVE_STATUS = ("digging", "furnishing", "decorating", "built")


def _stockpile(traits: dict) -> float:
    v = (traits or {}).get("stockpile", 0) or 0
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def stock_factor(traits: dict, cfg: dict | None = None) -> float:
    """Stockpile -> the reserve multiplier: 2^(v/50), kept to 0.25..4
    (`stockpile_signature` off: 2^(v/100), as before 0.105.47)."""
    if isinstance(cfg, dict) and not cfg.get("stockpile_signature", True):
        return 2 ** (_stockpile(traits) / 100)
    return max(0.25, min(4.0, 2 ** (_stockpile(traits) / 50)))


def reserve_cfg(cfg: dict, traits: dict) -> dict:
    """The config with the reserves scaled by the stock factor (the same
    dict when Stockpile is 0: nothing changes for a neutral fort)."""
    f = stock_factor(traits)
    if f == 1.0 or not cfg.get("stockpile_signature", True):
        return cfg
    out = dict(cfg)
    for k in SCALED:
        v = cfg.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = round(v * f, 2) if isinstance(v, float) else max(1, round(v * f))
    for k in SCALED_UP:
        v = cfg.get(k)
        if isinstance(v, int) and not isinstance(v, bool) and v > 0:
            out[k] = max(v, round(v * f))
    return out


def storage_room_size(traits: dict, size: int = 7) -> int:
    """A storage level's pile size for the slider: 11 at +100, 9 at +40, 5 at
    -40 or lower, else the size the rule asked for."""
    v = _stockpile(traits)
    return 11 if v >= 100 else 9 if v >= 40 else 5 if v <= -40 else size


def storage_levels(memory) -> int:
    """The storage levels the AI has dug or is digging (the atlas registry)."""
    reg = _d(_d(getattr(memory, "atlas", None)).get("registry"))
    return sum(1 for r in reg.values() if isinstance(r, dict) and r.get("kind") == "storage"
               and r.get("status") in LIVE_STATUS)


def reserve_storage_want(traits: dict, citizens: int, cfg: dict) -> int:
    """Storage levels a reserve-minded fort keeps for its citizens (0 under
    `reserve_storage_min`)."""
    if _stockpile(traits) < cfg["reserve_storage_min"] or not cfg.get("stockpile_signature", True):
        return 0
    f = stock_factor(traits)
    return min(cfg["reserve_vault_max"], 1 + math.ceil(citizens * (f - 1) / cfg["reserve_vault_citizens"]))


def _reserve_storage_rule(s: dict, memory, cfg: dict, traits: dict, proposals: list, notes: list) -> None:
    """A storage level for the reserves while the fort has fewer than it keeps."""
    citizens = int(_d(s.get("dwarves")).get("total") or 0)
    want = reserve_storage_want(traits, citizens, cfg)
    if memory is None or want <= 0 or young_fort(s, cfg) or citizens < cfg["reserve_vault_min_citizens"]:
        return
    have = storage_levels(memory)
    if have >= want:
        return
    open_ = [p for p in _d(s.get("projects")).get("open") or [] if isinstance(p, dict)]
    if any(p.get("kind") == "storage" for p in open_) or any(
            isinstance(p.action, dict) and p.action.get("kind") == "storage" for p in proposals):
        return
    gap = cfg["storage_gap_days"] / stock_factor(traits)
    last = getattr(memory, "storage_started", None)
    if isinstance(last, int) and 0 <= abs_tick(s) - last < gap * TICKS_PER_DAY:
        return
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return
    action = {"type": "start_project", "kind": "storage", "piles": list(RESERVE_PILES),
              "room_size": storage_room_size(traits)}
    where = masterplan.hint(memory, "storage", traits=traits, citizens=citizens) if masterplan.has_plan(memory) else None
    if where:
        action["plan"] = where
    proposals.append(Proposal(
        "reserve_storage", action,
        f"Stockpile {_stockpile(traits):g}: a fort that keeps reserves has {have} storage level(s) for "
        f"{citizens} dwarves (it keeps {want}): dig one more for food, drink, bars, blocks, cloth and wood", 6))


def reserves_pass(proposals: list, memory, traits: dict, cfg: dict | None = None) -> None:
    """Every storage level the rules propose gets the slider's pile size
    (a small-storage culture keeps its 5x5)."""
    from quirks import has_rule
    if isinstance(cfg, dict) and not cfg.get("stockpile_signature", True):
        return
    culture = getattr(memory, "culture", None) if memory is not None else None
    small = isinstance(culture, dict) and (has_rule(culture, "small_rooms") or has_rule(culture, "small_storage"))
    if small:
        return
    for p in proposals:
        a = p.action
        if isinstance(a, dict) and a.get("type") == "start_project" and a.get("kind") == "storage":
            size = a.get("room_size") if isinstance(a.get("room_size"), int) else 7
            a["room_size"] = storage_room_size(traits, size)
