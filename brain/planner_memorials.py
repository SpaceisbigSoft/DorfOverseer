"""(item7) The memorial slab orders that never end, and the walking ghosts
first.

Why (B, 24 Nov): the AI's own EngraveSlab orders (lua/ai-welfare.lua
slab_order) were made with frequency NONE, which DF never counts down: 14
stood at "1 left" and engraved their dead's slabs again and again (one
dwarf's 71 times, 136 Slab buildings put up), while the walking ghost's own
order (Inod "Oarzeal") waited behind eight others' jobs for a blank slab, and
the `slabs` rule put up "1 engraved memorial slab, none of them a walking
ghost's" 34 times in 2 hours.

  slabs_orders   the `supplies` section's memorial_orders_stale (orders for a
                 dead who has a memorial slab already) or memorial_orders_endless
                 (still wanted, never ending): prune_memorial_orders takes the
                 stale ones off with their jobs nobody works, makes the rest
                 once-only and puts the walking ghosts' orders first.

spare_slab_notes(s, notes) (item4): the engraved slabs whose dead has a memorial
up already (supplies.memorial_spare) are spares: never put up, so the `slabs`
rule (memorial_slabs counts none of them) does not fire for them; said once as
a note, with the dead who have more than one memorial up (dup_memorials). B,
24 Nov: three slabs put up for hf 42066 in an hour, 71 for one dwarf.

slabs_ahead_held(s): a walking ghost with no memorial slab at all
(supplies.ghosts_unslabbed) holds the memorial orders for the unreachable dead
(planner_welfare slabs_ahead): her slab is engraved first.
"""

from __future__ import annotations

from digest import _d
from util import int_or_zero as _int
from planner_core import AGENDA_THEMES, Proposal

__all__ = ["memorial_order_rules", "slabs_ahead_held", "spare_slab_notes"]

AGENDA_THEMES["slabs_orders"] = "end the memorial orders that never end"


def slabs_ahead_held(s: dict) -> bool:
    """A walking ghost has no memorial slab at all: no new memorial orders for others."""
    return _int(_d(s.get("supplies")).get("ghosts_unslabbed")) > 0


def memorial_order_rules(s: dict, proposals: list, notes: list) -> None:
    su = _d(s.get("supplies"))
    stale, endless = _int(su.get("memorial_orders_stale")), _int(su.get("memorial_orders_endless"))
    if stale <= 0 and endless <= 0:
        return
    ghosts = _int(_d(s.get("dead")).get("ghosts"))
    unslabbed = _int(su.get("ghosts_unslabbed"))
    parts = []
    if stale:
        parts.append(f"{stale} memorial slab order(s) for dead who have their slab already engrave it again "
                     "and again (DF never ends them)")
    if endless:
        parts.append(f"{endless} still wanted never end")
    tail = (f"; {unslabbed} walking ghost(s) wait for their own slab behind them" if unslabbed else "")
    proposals.append(Proposal("slabs_orders", {"type": "prune_memorial_orders"},
                              "; ".join(parts) + tail + ": take the spent ones off, the rest once each, "
                              "the ghosts' first", 1 if ghosts else 3))


def spare_slab_notes(s: dict, notes: list) -> None:
    """(item4) The spare memorial slabs, left lying, and the dead with two or more up: notes only."""
    su = _d(s.get("supplies"))
    spare, dup = _int(su.get("memorial_spare")), _int(su.get("dup_memorials"))
    if spare > 0:
        notes.append(f"{spare} engraved memorial slab(s) are spares (their dead have a memorial up already): "
                     "left where they lie, not put up")
    if dup > 0:
        notes.append(f"{dup} dead have more than one memorial slab up (one lays a ghost; the rest are left standing)")
