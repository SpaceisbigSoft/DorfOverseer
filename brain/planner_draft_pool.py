"""(R30c item24) squad_fill's pool: who the bridge's fill could draft, from the
report's `military.draft_ids` (lua/ai-military-draft.lua draft_pool_ids)."""

from __future__ import annotations


def draft_pool_left(mil: dict, avoid) -> int | None:
    """(R30c item24) How many dwarves squad_fill could draft that `avoid` leaves:
    the report's `military.draft_ids` (ai-military-draft draft_pool_ids, at the
    fill's loosest) less those ids; None when not known (an older bridge, or the
    list cut off at its cap: `draft_pool` past its length)."""
    pool = mil.get("draft_pool")
    ids = mil.get("draft_ids")
    if isinstance(ids, dict) and not ids:
        ids = []                      # an empty Lua table
    if not isinstance(pool, int) or isinstance(pool, bool) or not isinstance(ids, list) or len(ids) != pool:
        return None
    skip = {int(x) for x in (avoid or []) if isinstance(x, int) or str(x).isdigit()}
    return sum(1 for i in ids if isinstance(i, int) and i not in skip)
