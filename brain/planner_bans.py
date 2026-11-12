"""(0.105.41, item 8) The nobles' export bans followed.

DF's nobles (the mountainhome's monarch, or a baron's own) can forbid the
fort to export some goods: a mandate of the Export kind (the `mandates`
report's kind "Export"; lua/ai-trade.lua's `trade.bans` while a depot
stands). Breaking one gets the noble's punishment. lua/ai-trade.lua keeps
the banned goods off the caravan trade itself (lua/ai-bans.lua: never taken
to the depot, never offered on the trade screen); here:

  * the bans are said while a caravan is coming or at the depot, with how
    many goods were kept home for them;
  * the goods a caravan's agreement pays well for are not made for export
    when a ban covers them (planner_world._export_rule asks banned_items)."""

from __future__ import annotations

from digest import _d, _l

__all__ = ["export_bans", "banned_items", "_export_bans_notes"]


def export_bans(s: dict) -> list[dict]:
    """The export bans in force: {item, material, by, days_left}, from the
    trade report's bans, else the `mandates` report's Export ones."""
    tr = _d(s.get("trade"))
    bans = [b for b in _l(tr.get("bans")) if isinstance(b, dict) and b.get("item")]
    if bans:
        return bans
    out = []
    for m in _l(s.get("mandates")):
        if isinstance(m, dict) and m.get("kind") == "Export" and m.get("item"):
            if isinstance(m.get("days_left"), int) and m["days_left"] <= 0:
                continue
            out.append({"item": m.get("item"), "material": m.get("material"), "by": m.get("by"),
                        "days_left": m.get("days_left")})
    return out


def banned_items(s: dict) -> set:
    """DF item type names a ban in force covers (any material: a ban on one
    material keeps the kind off the export orders too, the safe side)."""
    return {str(b["item"]).upper() for b in export_bans(s)}


def _ban_words(b: dict) -> str:
    what = str(b.get("item") or "?").lower().replace("_", " ")
    if b.get("material"):
        what = f"{str(b['material']).lower()} {what}"
    by = f" (by {b['by']}" if b.get("by") else " ("
    left = f"{b['days_left']} days left)" if isinstance(b.get("days_left"), int) else "in force)"
    return what + by + ("; " if b.get("by") else "") + left


def _export_bans_notes(s: dict, notes: list) -> None:
    """While a caravan is coming or here: the export bans, and the goods
    kept home for them."""
    bans = export_bans(s)
    tr = _d(s.get("trade"))
    if not bans or not _l(tr.get("caravans")):
        return
    kept = int(tr.get("banned_kept") or 0)
    notes.append("the nobles ban exporting " + "; ".join(_ban_words(b) for b in bans[:4])
                 + (f" and {len(bans) - 4} more" if len(bans) > 4 else "")
                 + ": those goods are kept off the caravan trade"
                 + (f" ({kept} kept home)" if kept else ""))
