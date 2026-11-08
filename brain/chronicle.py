"""The chronicle: the fort's story as it happened, in short entries.

    chronicle.add(memory, state, "siege", "a siege hardened the fort")
    chronicle.lines(memory, 4)           # newest first, for the panel and the strategist
    chronicle.consolidate(memory, year)  # small entries over two years old become one line a year

It keeps the fort's whole history: eras, sieges, slain beasts, quirks earned
and lost, caverns and magma found, gates walled, levels finished, lessons
learned. The culture history (brain/culture.py) is stored beside it in the
same part of the save. Major entries are kept for ever; minor ones (a level
finished, a gate walled) are summed up a year at a time once they are two
years old, so a long fort's chronicle stays a readable size.

Kept in memory.chronicle: {"entries": [{"y", "d", "k", "t"}], "years": {year: {kind: count}}}.
A script writes these in plain words; the AI-written chronicle
(brain/storyteller.py, off by default) adds a "story" paragraph a season.
"""

from __future__ import annotations

MAX_ENTRIES = 300
MINOR = {"built": ("level finished", "levels finished"), "gate": ("gate walled", "gates walled"),
         "learned": ("lesson learned", "lessons learned"), "registry": ("change noticed", "changes noticed"),
         "phase": ("change of phase", "changes of phase")}
MAJOR = {"era", "siege", "beast", "quirk", "found", "founded", "death", "plan", "story"}


def _state(memory) -> dict:
    c = memory.chronicle if isinstance(memory.chronicle, dict) else {}
    memory.chronicle = c
    if not isinstance(c.get("entries"), list):
        c["entries"] = []
    if not isinstance(c.get("years"), dict):
        c["years"] = {}
    return c


def _date(state: dict) -> str:
    d = state.get("date") or {}
    return f"{d.get('day')} {d.get('month')} y{d.get('year')}"


def add(memory, state: dict, kind: str, text: str) -> dict | None:
    """One entry; the same words on the same day are kept once."""
    c = _state(memory)
    text = " ".join(str(text).split())[:140]
    if not text:
        return None
    year = (state.get("date") or {}).get("year")
    e = {"y": year, "d": _date(state), "k": kind, "t": text}
    for old in c["entries"][-12:]:
        if old.get("d") == e["d"] and old.get("t") == text:
            return None
    c["entries"].append(e)
    if len(c["entries"]) > MAX_ENTRIES:
        # over the limit even after consolidating: the oldest minor ones go first
        minor = [i for i, x in enumerate(c["entries"]) if x.get("k") not in MAJOR]
        drop = set(minor[:len(c["entries"]) - MAX_ENTRIES])
        c["entries"] = [x for i, x in enumerate(c["entries"]) if i not in drop][-MAX_ENTRIES:]
    return e


def rewind(memory, year: int) -> None:
    """An older save was loaded: forget entries from years after it."""
    c = _state(memory)
    c["entries"] = [e for e in c["entries"] if not isinstance(e.get("y"), int) or e["y"] <= year]
    c["years"] = {k: v for k, v in c["years"].items() if not str(k).isdigit() or int(k) <= year}


def consolidate(memory, year: int) -> int:
    """Minor entries more than two years old become a count for their year."""
    c = _state(memory)
    keep, n = [], 0
    for e in c["entries"]:
        y = e.get("y")
        if e.get("k") in MINOR and isinstance(y, int) and year - y > 2:
            counts = c["years"].setdefault(str(y), {})
            counts[e["k"]] = counts.get(e["k"], 0) + 1
            n += 1
        else:
            keep.append(e)
    c["entries"] = keep
    return n


def lines(memory, limit: int = 4, kinds: set | None = None) -> list[str]:
    c = _state(memory)
    out = []
    for e in reversed(c["entries"]):
        if kinds and e.get("k") not in kinds:
            continue
        out.append(f"{e.get('d')}: {e.get('t')}")
        if len(out) >= limit:
            break
    return out


def year_lines(memory, limit: int = 3) -> list[str]:
    """'year 150: 4 levels finished, 2 gates walled' for the summed-up years."""
    c = _state(memory)
    out = []
    for y in sorted(c["years"], key=lambda k: int(k) if str(k).isdigit() else 0, reverse=True)[:limit]:
        parts = []
        for k, n in sorted(c["years"][y].items()):
            one, many = MINOR.get(k, (k, k))
            parts.append(f"{n} {one if n == 1 else many}")
        out.append(f"year {y}: " + ", ".join(parts))
    return out
