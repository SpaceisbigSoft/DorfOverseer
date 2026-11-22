"""(0.105.47) Cavern wells made safe (R2, I7d "Cavern wells").

The AI's cavern wells killed 11 dwarves in the 12-14 Nov run: falls down a
fresh shaft's column minutes after it was dug, drownings in the lake 1-5
tiles from a shaft dug minutes before (mostly miners), dwarves stranded
under a well's landing with no path back (A's Nomal, later killed by a
forgotten beast). E placed 13 cavern wells in 6 hours; the seal found "no
door or hatch on the way down to lock"; the stair lid was locked with no
look below. The bridge's side is lua/ai-well-safety.lua (and the shaft dug
from the bottom up in ai-builder-wells.lua). Here:

  * `cavern_well_wait`: why no cavern well is begun now (one is being dug or
    built; one was given up within `cavern_well_cooldown_days`), read from
    the bridge's book; planner_wells asks it before proposing one, and the
    action carries the cooldown and the site cap (`cavern_well_site_tries`)
    so the bridge holds to the same numbers;
  * `_well_safety_rule`: the `well_safety` step whenever the bridge lists
    something to do (the watcher not running, a shaft's column not yet
    restricted, a door due at a gallery's fort end, the next level of a
    shaft dug from the bottom up); the watcher's log of citizens beside an
    open shaft or turned up in the cavern under a well said as notes;
  * the rescue: a citizen stranded in the cavern under a well (no path, out
    `well_rescue_after_ticks`) gets `well_rescue` (the well's door unlocked,
    or a stair dug out to them), before any alarm; it waits while a danger is
    near them (the bridge checks again); `well_rescue_covers` tells
    planner_gates which cavern rows are taken care of here.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (EMERGENCY, PLANNER_CONFIG, STEER_PROTECTED, TICKS_PER_DAY, Proposal,
                          abs_tick)

__all__ = ["_well_safety_rule", "cavern_well_wait", "well_rescue_rows", "well_rescue_covers", "well_under",
           "WELL_SAFETY_TODO"]

# a rescue is a life: no action limit, never held by the strategist (it paces itself: the bridge waits for a beast)
EMERGENCY.update({"well_rescue"})
STEER_PROTECTED.update({"well_rescue", "well_safety"})

WELL_SAFETY_TODO = {
    "watch": "start the cavern wells' watcher (the column, who stands beside an open shaft or under a well)",
    "traffic": "restrict traffic on a cavern well's shaft column while it is dug",
    "door": "put a door at the fort end of a cavern well's gallery (a way into the caverns the seal can lock)",
    "level": "dig the next level of a cavern well's shaft (from the bottom up, nobody in its column)",
    # (K48-K4) the rescue stair was a walk from the cavern floor into the well's stairs for good
    "rescue_close": "close a cavern well's rescue stair now nobody is on it (a hatch on its top step, locked)",
}


from util import conf_soft as _c  # noqa: E402  (r6 c2) was a copy here


def _ws(s: dict) -> dict:
    return _d(s.get("well_safety"))


def cavern_well_wait(s: dict, cfg: dict | None = None) -> str:
    """Why no new cavern well is begun now ("" when one may be): one being
    dug or built (one at a time), or one given up within the cooldown. The
    bridge's own book (its cooldown counted from the given-up well's tick)."""
    book = _d(_ws(s).get("book"))
    active = [x for x in _l(book.get("active")) if isinstance(x, int)]
    if active:
        return f"a cavern well is already being dug or built (project {active[0]}): one at a time"
    days = int(_c(cfg, "cavern_well_cooldown_days") or 0)
    last = book.get("last_gone")
    if days > 0 and isinstance(last, int):
        left = days * TICKS_PER_DAY - (abs_tick(s) - last)
        if 0 < left <= days * TICKS_PER_DAY:
            return (f"a cavern well was given up {(abs_tick(s) - last) // TICKS_PER_DAY} day(s) ago: the next one "
                    f"only after {-(-left // TICKS_PER_DAY)} more day(s) (one hole into the cavern at a time, "
                    "not one after another)")
    return ""


def well_under(s: dict, x: int, y: int, z: int, cfg: dict | None = None) -> dict | None:
    """The cavern well (the bridge's row) whose shaft (x, y) is within
    `well_rescue_near` across and above the spot, nearest first."""
    near = int(_c(cfg, "well_rescue_near") or 15)
    best, bd = None, None
    for w in _l(_ws(s).get("wells")):
        w = _d(w)
        if not all(isinstance(w.get(k), int) for k in ("x", "y", "hz")):
            continue
        d = max(abs(w["x"] - x), abs(w["y"] - y))
        if z < w["hz"] and d <= near and (bd is None or d < bd):
            best, bd = w, d
    return best


def well_rescue_rows(s: dict, cfg: dict | None = None) -> list:
    """(row, well) for each citizen stranded in a cavern with no path back,
    under a cavern well, out `well_rescue_after_ticks` or more."""
    after = int(_c(cfg, "well_rescue_after_ticks") or 0)
    out = []
    for r in _l(_d(s.get("entrances")).get("stranded")):
        if not isinstance(r, dict) or not r.get("in_cavern") or r.get("cause") != "no_path":
            continue
        if not all(isinstance(r.get(k), int) for k in ("x", "y", "z")):
            continue
        if int(r.get("out_ticks") or 0) < after:
            continue
        w = well_under(s, r["x"], r["y"], r["z"], cfg)
        if w is not None:
            out.append((r, w))
    return out


def well_rescue_covers(s: dict, r: dict, cfg: dict | None = None) -> bool:
    """A stranded row this module takes care of (planner_gates leaves it out
    of its "the AI can't reach them" line)."""
    if not isinstance(r, dict) or not r.get("in_cavern") or r.get("cause") != "no_path":
        return False
    if not all(isinstance(r.get(k), int) for k in ("x", "y", "z")):
        return False
    return well_under(s, r["x"], r["y"], r["z"], cfg) is not None


def _where(r: dict, off: int) -> str:
    return f"{r.get('name') or 'a dwarf'} (x{r.get('x')} y{r.get('y')} elevation {(r.get('z') or 0) + off})"


def _well_safety_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    ws = _ws(s)
    if not ws:
        return
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) else 0
    if ws.get("watch_error"):
        notes.append(f"the cavern wells' watcher failed in the game ({str(ws['watch_error'])[:120]}): "
                     "it is started again with the next well_safety step")
    # the step: whatever the bridge lists to do
    todo = [t for t in _l(ws.get("todo")) if t in WELL_SAFETY_TODO]
    if todo:
        proposals.append(Proposal("well_safety", {"type": "well_safety"},
                                  "; ".join(WELL_SAFETY_TODO[t] for t in todo), 2))
    # what the bridge saw: the watch's log (new lines only)
    seen = int(_d(getattr(memory, "last_fired", None)).get("well_safety_log") or 0) if memory is not None else 0
    newest = seen
    for e in _l(ws.get("log")):
        e = _d(e)
        t = e.get("tick")
        if isinstance(t, int) and t > seen and e.get("kind") in ("in_shaft", "beside_shaft", "under_well", "suspended"):
            notes.append(f"the cavern wells' watcher: {str(e.get('text'))[:200]}")
        if isinstance(t, int):
            newest = max(newest, t)
    if memory is not None and isinstance(getattr(memory, "last_fired", None), dict) and newest > seen:
        memory.last_fired["well_safety_log"] = newest
    # who is held up below
    for w in _l(ws.get("wells")):
        w = _d(w)
        if w.get("below_lid") and w.get("phase") != "dig":
            notes.append(f"cavern well {w.get('project_id')}: {w.get('below_lid')} is below its stair lid and gate, "
                         "so neither is locked or shut on them (the AI tries again when they are up)")
    # the rescue, before any alarm
    for r, w in well_rescue_rows(s, cfg):
        danger = r.get("danger_near")
        if isinstance(danger, (int, float)) and danger <= int(_c(cfg, "stranded_danger_near") or 30):
            notes.append(f"{_where(r, off)} is stranded in the cavern under cavern well {w.get('project_id')}, but a "
                         f"danger is {danger} tiles from them: the way up is opened once it is gone")
            continue
        proposals.append(Proposal("well_rescue",
                                  {"type": "well_rescue", "x": r["x"], "y": r["y"], "z": r["z"],
                                   "project_id": w.get("project_id")},
                                  f"{_where(r, off)} is stranded in the cavern under cavern well "
                                  f"{w.get('project_id')} with no way back: open the well's way up for them "
                                  "(its door unlocked, or a stair dug out from its stairs down to them)", -1))
