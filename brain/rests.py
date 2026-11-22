"""(r5 p2) A ghost laid to rest is no death.

DF tells a ghost laid to rest by a slab twice over: an announcement
("Urist, Ghostly Miner has been put to rest.", type CITIZEN_DEATH, which the
bridge's report reader filed under the topic `ghost`) and, often, the unit's
death again (DFHack's UNIT_DEATH fires once more). The bridge marks the
second death `again` when it knows the unit was told before, but that memory
is lost when DF restarts and the age check needs DF's incident. In the 15-16
Nov run B journaled 11 such deaths, and every "put to rest" announcement
counted as a ghost risen (seasons.csv, the scorecard, a strategist review).

    mark_rests(events, told)   each event as it should be read: a rest is
                               `rest: True` (a death told again also `again`,
                               a rest announcement topic "rest")
    is_rest(ev)                a ghost laid to rest (any of its shapes)
    citizen_death(ev)          a citizen's new death (no rest, no animal)

Every count of citizens' deaths (crisis mode, timeline/seasons.csv, metrics,
the scorecard, the strategist, culture, visitors) goes through citizen_death.
"""

from __future__ import annotations

REST_WORDS = ("put to rest", "laid to rest")
TOLD_KEEP = 2000          # [unit id, tick] of citizens told dead, kept in memory (the newest)
YEAR_TICKS = 403200
REWIND_SLACK = 1200       # a day: the report's date and the event's tick may differ a little


def _on() -> bool:
    try:
        from planner_config import PLANNER_CONFIG
        return PLANNER_CONFIG.get("r5p2_rests", True) is not False
    except Exception:  # noqa: BLE001
        return True


def rest_text(text) -> bool:
    low = " ".join(str(text or "").split()).lower()
    return any(w in low for w in REST_WORDS)


def is_rest(ev) -> bool:
    """A ghost laid to rest: the journal's `laid_to_rest`, a death told again
    or of a ghost, an announcement of the topic `rest` or one saying "put to
    rest" (an older bridge filed it under `ghost`)."""
    if not isinstance(ev, dict):
        return False
    k = ev.get("kind")
    if ev.get("rest") or k in ("laid_to_rest", "rest"):
        return True
    if k == "death":
        return bool(ev.get("again") or (ev.get("ghost") and _on()))
    if k == "report":
        return ev.get("topic") == "rest" or (_on() and rest_text(ev.get("text")))
    return False


def citizen_death(ev) -> bool:
    """A citizen's new death: own civ, no animal, and no ghost laid to rest."""
    return (isinstance(ev, dict) and ev.get("kind") == "death" and bool(ev.get("own_civ"))
            and not ev.get("animal") and not is_rest(ev))


def _who(name) -> str:
    """The first two words of a name, for matching an announcement to a unit
    ("Zulban Dakostag, Ghostly Axedwarf" and "Zulban Dakostag, Axedwarf")."""
    head = " ".join(str(name or "").split()).split(",")[0].split(' "')[0]
    return " ".join(head.split()[:2]).lower()


def _ev_tick(e: dict):
    y, t = e.get("year"), e.get("tick")
    if isinstance(y, int) and isinstance(t, int) and not isinstance(y, bool):
        return y * YEAR_TICKS + t
    return None


def mark_rests(events, told=None, now=None) -> list:
    """The events as they should be read (new dicts where changed):
    - an announcement of a ghost put to rest: topic "rest", rest True;
    - a death of a unit already told dead (`told`, the memory's list of
      [unit id, tick], kept across DF restarts), of a ghost, told `again` by
      the bridge, or named by a rest announcement in the same batch: again
      True, rest True;
    - every other citizen's death adds [unit id, tick] to `told` (a list).
    `now` (the game's absolute tick): deaths told after it are forgotten
    first (an older save was loaded: they never happened, and the dwarf may
    die for real later). With r5p2_rests off, the events come back as they were."""
    events = [e for e in (events or [])]
    if not _on():
        return events
    if isinstance(told, list):
        keep = [x for x in told if isinstance(x, list) and len(x) == 2
                and (not isinstance(now, int) or not isinstance(x[1], int) or x[1] <= now + REWIND_SLACK)]
        told[:] = keep
    rest_names = {_who(e.get("text").split(" has been")[0])
                  for e in events if isinstance(e, dict) and e.get("kind") == "report"
                  and isinstance(e.get("text"), str) and rest_text(e.get("text"))}
    seen = {x[0] for x in told} if isinstance(told, list) else set()
    out = []
    for e in events:
        if not isinstance(e, dict):
            out.append(e)
            continue
        if e.get("kind") == "report" and (e.get("topic") == "rest" or rest_text(e.get("text"))):
            extra = {"was_topic": e["topic"]} if e.get("topic") not in (None, "rest") else {}
            out.append(dict(e, topic="rest", rest=True, **extra))
            continue
        if e.get("kind") == "death" and e.get("own_civ") and not e.get("animal"):
            uid = e.get("unit_id")
            if (e.get("again") or e.get("ghost") or (uid is not None and uid in seen)
                    or (rest_names and _who(e.get("name")) in rest_names)):
                out.append(dict(e, again=True, rest=True))
                continue
            if uid is not None and isinstance(told, list):
                tick = _ev_tick(e)
                told.append([uid, tick if tick is not None else now])
                seen.add(uid)
        out.append(e)
    if isinstance(told, list) and len(told) > TOLD_KEEP:
        del told[:-TOLD_KEEP]
    return out
