"""(item7) The great dangers below that the fort hasn't seen yet.

Why (B, 24 Nov): three forgotten beasts lived in B's caverns (Bonephantom in
Cavern1, Paddlecrevice and Lonelyweird, both fliers, in Cavern2), every one on
tiles the fort had not revealed. The bridge leaves such units out of `deep`
dangers and `others_on_map` threats (the fort can't see them), so the seal
rule saw no beast at all: a seal put on while one showed would have been
opened again "no forgotten beast left in the caverns" with three below, and a
beast that could walk into the fort was not sealed out until it came into
sight. The bridge now sends them apart (`deep.unseen`: kind, layer, whether
it can walk to the dwarves, flier), and the seal rule (planner_threats
_cavern_beasts) uses them:

  * one that can walk to the dwarves is sealed out as a seen one is (no kill
    plan for it: a fight waits until it is seen);
  * any of them keeps the ways down locked (no "no beast left" opening);
  * the rest are said in a note (none can walk to the dwarves).
"""

from __future__ import annotations

from digest import _d, _l

__all__ = ["unseen_great", "unseen_words"]

UNSEEN_KINDS = ("forgotten beast", "titan", "megabeast", "demon")   # planner_threats GREAT_KINDS


def unseen_great(s: dict) -> list:
    """The unseen great dangers in the caverns (a forgotten beast anywhere),
    less any held in a lure pocket."""
    held = set(_l(_d(s.get("lures")).get("held_beasts")))
    out = []
    for x in _l(_d(s.get("deep")).get("unseen")):
        if not isinstance(x, dict) or x.get("kind") not in UNSEEN_KINDS or x.get("id") in held:
            continue
        if str(x.get("layer") or "").startswith("Cavern") or x.get("kind") == "forgotten beast":
            out.append(x)
    return out


def unseen_words(rows: list, most: int = 3) -> str:
    """'Bonephantom (forgotten beast, Cavern1), Paddlecrevice (forgotten beast, flies, Cavern2)'"""
    out = []
    for x in rows[:most]:
        name = str(x.get("name") or "a great beast")
        bits = [str(x.get("kind") or "great beast")] + (["flies"] if x.get("flier") else []) + (
            [str(x["layer"])] if x.get("layer") else [])
        out.append(f"{name} ({', '.join(bits)})")
    more = len(rows) - most
    return ", ".join(out) + (f" and {more} more" if more > 0 else "")
