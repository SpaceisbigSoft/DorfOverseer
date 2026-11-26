"""(R32 c) A great danger judged too strong is not gone out at.

F (26 Nov 04:55-04:58): a Hydra the planner judged too strong (the squads
42 against 48: the dwarves hid, two squads at the choke) was sent at by
squad_attack a minute later: fight_or_hide's bar was lowered x0.8 for a
moment ("falling back" a few tiles), all three squads went, 5 soldiers died
in 70 s, and squad_recall called them back "too weak now" at 0.7x. One
judgement for the sortie and the recall now:

  * the military rules book their verdict on the great dangers in reach
    (memory.holdfast["great_hold"]: too strong -> held, until a fight at
    them begins or they leave the map);
  * fight_or_hide (the military rules, the hiding rule's fight_judged and
    the recall all read it) goes out at a held one only at the full bar
    (planner_matchup.fight_bar), never one lowered for a moment, and not at
    the 3/4 bar of a fight begun earlier (that bar keeps a fight going, it
    doesn't begin one again);
  * one inside the fort is judged as before: there holding the choke
    protects nobody;
  * the words "too strong to go out at (N against M, Kx needed): the squads
    hold the choke" for the notes and the shelter_squads reason.

And the player (26 Nov): "never attack" is no sortie outside; an enemy
inside the walls is fought (planner_military, planner_army.hiding), a great
one only when the squads are strong enough (else the choke is held).
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import abs_tick

__all__ = ["GREAT_HOLD_KEY", "great_inside", "great_held", "note_great_hold", "too_strong_words", "hold_bar"]


GREAT_HOLD_KEY = "great_hold"      # (R32 c) memory.holdfast[...]: {great danger id (str): tick judged too strong}


def great_inside(s: dict, rows) -> set:
    """(R32 c) The ids of these threat rows that are inside the fort (the
    gate scan's intruders inside, the hunt's "inside" targets, a row's own
    `inside`): there holding the choke protects nobody."""
    from planner_holdfast import _inside_ids
    ins = _inside_ids(s)
    return {t.get("id") for t in rows if isinstance(t, dict) and t.get("id") is not None
            and (t.get("id") in ins or t.get("inside") is True)}


def great_held(memory, rows) -> set:
    """(R32 c) The ids of these great dangers the military rules judged too
    strong to go out at (and haven't gone out at since)."""
    hf = getattr(memory, "holdfast", None) if memory is not None else None
    book = _d(_d(hf).get(GREAT_HOLD_KEY))
    return {t.get("id") for t in rows if isinstance(t, dict) and str(t.get("id")) in book}


def note_great_hold(s: dict, memory, great: list, fight: bool) -> None:
    """(R32 c) The military rules' own verdict on the great dangers in reach,
    booked: too strong (not fought) -> held, until a fight at them begins or
    they leave the map. fight_or_hide reads it (no sortie from a hold at a
    bar lowered for a moment: F's Hydra, 26 Nov)."""
    if memory is None or not isinstance(getattr(memory, "holdfast", None), dict):
        return
    book = memory.holdfast.get(GREAT_HOLD_KEY)
    book = dict(book) if isinstance(book, dict) else {}
    present = {str(t.get("id")) for t in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(t, dict)}
    book = {k: v for k, v in book.items() if k in present}
    for t in great:
        k = str(t.get("id"))
        if fight:
            book.pop(k, None)
        else:
            book.setdefault(k, abs_tick(s))
    if book:
        memory.holdfast[GREAT_HOLD_KEY] = book
    else:
        memory.holdfast.pop(GREAT_HOLD_KEY, None)


def too_strong_words(info: dict, choke: bool = True) -> str:
    """(R32 c) The reason words for a great danger judged too strong to go
    out at (`choke`: the squads have a post between it and the shelter)."""
    info = _d(info)
    if not isinstance(info.get("need"), (int, float)):
        return ""
    return (f"too strong to go out at ({float(info.get('army') or 0):.0f} against {float(info['need']):.0f}, "
            f"{float(info.get('bar') or 0):g}x needed)"
            + (": the squads hold the choke" if choke else ": the squads stay in"))


def hold_bar(s: dict, memory, cfg: dict, great: list, bar: float, why: str, info: dict | None = None,
             army: float = 0.0, need: float = 0.0, ratio: float = 0.0) -> tuple[float, str, bool]:
    """(bar, why, held) for fight_or_hide: held as too strong and outside the
    fort, the full bar (fight_bar), not one lowered for a moment. `info`
    (when given) is filled with {army, need, ratio, bar, held, inside}."""
    from planner_matchup import fight_bar
    inside = great_inside(s, great)
    held = bool(great_held(memory, great)) and not inside
    if held:
        fb = fight_bar(great, cfg)
        if float(fb["bar"]) > bar:
            bar = float(fb["bar"])
            why = f"{fb['why']}; judged too strong before: the full bar to go out at it"
    if info is not None:
        info.update(army=army, need=need, ratio=ratio, bar=bar, held=held,
                    inside=sorted(i for i in inside if isinstance(i, int)))
    return bar, why, held
