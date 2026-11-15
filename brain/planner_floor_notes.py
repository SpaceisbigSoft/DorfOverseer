"""planner_floor_notes (layout B): what the hallway-first floors are doing, in
words. Reads one thing, the report's `floors` section
(lua/ai-builder-floorstore.lua `floors_report`: the mode, each floor's hall,
the tags found full, the fallback count and the last placement try), and
says it in two places:

- `_floor_notes`: a planner pass that only speaks. A level that went to the
  classic placement after the floors refused it (said for `floor_note_days`
  game days after it happened), and a floor that has no more room for a
  district. Two notes a cycle at most. It proposes nothing and changes no
  memory; a fort with no floors hears nothing (plan()'s notes are part of
  the committed plan snapshots). A level with `no_hall` is no note: a
  built-up fort has several, for good.
- `floors_line`: one digest line, "" when there is no floor.

Everything is computed from the section alone, each cycle anew.
"""

from __future__ import annotations

import re

from digest import _d, _l, game_text

__all__ = ["floors_view", "floors_line", "_floor_notes", "NOTES_MAX", "TICKS_PER_DAY"]

TICKS_PER_DAY = 1200
NOTES_MAX = 2                # notes a cycle, at most
WHY_NOTE = 120               # characters of the builder's reason in a note
WHY_LINE = 80                # ... and in the digest line
_WORD_RE = re.compile(r"^[a-z_]{1,24}$")


def _int(v) -> int:
    """A whole number from the report, 0 for anything else (a bool is not a count)."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v == v and abs(v) < 1e15:
        return int(v)
    return 0


def _word(v) -> str:
    """A kind or a tag from the report as a word for a sentence ("" when it isn't one)."""
    return v.replace("_", " ").strip() if isinstance(v, str) and _WORD_RE.match(v) else ""


def _n(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def floors_view(s: dict) -> dict | None:
    """The `floors` section when it is a dict without "error", else None."""
    v = s.get("floors") if isinstance(s, dict) else None
    return v if isinstance(v, dict) and "error" not in v else None


def _rows(f: dict) -> list[dict]:
    return [r for r in _l(f.get("list")) if isinstance(r, dict)]


def _failed_last(f: dict) -> dict | None:
    """The last placement try when it did not go onto a floor (`ok` is false), else None."""
    last = f.get("last")
    return last if isinstance(last, dict) and last.get("ok") is False else None


def _why(last: dict, n: int) -> str:
    w = last.get("why")
    return f" ({game_text(w, n)})" if isinstance(w, str) and w.strip() else ""


def _now(s: dict) -> int | None:
    """The state's date as an absolute tick (planner_core.abs_tick), None when it can't be read."""
    try:
        from planner_core import abs_tick
        t = abs_tick(s)
    except Exception:  # noqa: BLE001
        return None
    return t if isinstance(t, int) and not isinstance(t, bool) else None


def _fallback_note(f: dict, s: dict, cfg: dict) -> str | None:
    last = _failed_last(f)
    if last is None:
        return None
    tick, now = last.get("tick"), _now(s)
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) or now is None:
        return None
    try:
        days = float(cfg.get("floor_note_days", 3))
    except (TypeError, ValueError):
        days = 3.0
    limit = days * TICKS_PER_DAY
    if not (days == days) or limit < 0 or not (-limit <= now - tick <= limit):   # NaN; older than the days (or a tick from another calendar)
        return None
    kind = _word(last.get("kind"))
    return f"{'the ' + kind if kind else 'a'} level went to the classic placement, not a floor{_why(last, WHY_NOTE)}"


def _full_note(f: dict) -> str | None:
    """The lowest-numbered floor with a hall that is full for a district."""
    best = None
    for r in _rows(f):
        if r.get("no_hall") is True:
            continue
        rid = r.get("id")
        if isinstance(rid, bool) or not isinstance(rid, int):
            continue
        tags = []
        for t in _l(r.get("full")):
            w = _word(t)
            if w and w not in tags:
                tags.append(w)
        if tags and (best is None or rid < best[0]):
            best = (rid, r, tags)
    if best is None:
        return None
    rid, r, tags = best
    elev = r.get("elevation")
    where = f" (elevation {_int(elev)})" if isinstance(elev, (int, float)) and not isinstance(elev, bool) else ""
    return (f"floor {rid}{where} has no more room for {' and '.join('the ' + t for t in tags)}: "
            f"the next {' or '.join(tags)} level goes to another floor")


def _floor_notes(s: dict, memory, cfg: dict, notes: list) -> None:
    """(layout B) A planner pass that only speaks: a level that fell back to
    the classic placement (for `floor_note_days` after it happened), a floor
    full for a district (one a cycle, the lowest floor id). Two notes at
    most. Proposes nothing, changes no memory (it is not read), says nothing
    without floors, and never raises."""
    try:
        f = floors_view(s)
        if f is None or not (_rows(f) or isinstance(f.get("last"), dict)):
            return
        said = [n for n in (_fallback_note(f, s, _d(cfg)), _full_note(f)) if n]
        notes.extend(said[:NOTES_MAX])
    except Exception:  # noqa: BLE001  (words only: an odd section is silence, never a failed rule's note)
        return


def floors_line(s: dict) -> str:
    """FLOORS 3 floors, 41 rooms on 310 tiles of hall | 2 levels with no room
    for a hall | classic placements 2 | last: dining not on a floor (floor 3:
    no room). Each part after the first only when there is something to say;
    "" with no section, an error in it, or nothing in `list` and no fallbacks."""
    try:
        f = floors_view(s)
        if f is None:
            return ""
        rows, fallbacks = _rows(f), max(0, _int(f.get("fallbacks")))
        if not rows and not fallbacks:
            return ""
        no_hall = sum(1 for r in rows if r.get("no_hall") is True)
        parts = [f"FLOORS {_n(len(rows) - no_hall, 'floor')}, {_n(max(0, _int(f.get('rooms'))), 'room')}"
                 f" on {_n(max(0, _int(f.get('hall_tiles'))), 'tile')} of hall"]
        if no_hall:
            parts.append(f"{_n(no_hall, 'level')} with no room for a hall")
        if fallbacks:
            parts.append(f"classic placements {fallbacks}")
        last = _failed_last(f)
        if last is not None:
            parts.append(f"last: {_word(last.get('kind')) or 'a level'} not on a floor{_why(last, WHY_LINE)}")
        return " | ".join(parts)
    except Exception:  # noqa: BLE001  (a digest line never stops the digest)
        return ""
