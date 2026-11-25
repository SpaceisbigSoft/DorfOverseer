"""planner_social_places (0.105.113 item9): the taverns and temples drawn
together when the fort has more than its size needs.

B "Monastery", 24 Nov 23:30-23:40 (state.json, probe i9-rec): 35 citizens,
94 a season before (timeline.csv), and every place built for the 94 still
open: 3 taverns, 5 temples (two to all gods, three to one god each), 2
guildhalls, a library, 4 hospitals. DF sends each idle dwarf to one of them:
11 idle in 6 locations and the barracks, never more than 3 in one, 4 in no
zone. 26 of 35 badly missed friends (8 of them soldiers), 21 of those with
3 or more close friends they never met; 40-50% of the fort unhappy or
worse. Drink was not short (DrinkAlcohol badly 0), the squads were off duty
(0.105.97's leisure), the recreation burrow already kept one tavern and one
temple (0.105.110) but held 2-8 of the 35.

So: one tavern and one temple for every `social_places_per` (40) citizens
(one at least, `social_halls_max` at most); the others' zones made inactive
(DF's zone screen) by the bridge (lua/ai-society-burrows.lua
social_consolidate: the best kept, as the recreation burrow ranks them, the
player's own choices never touched: `player_kept`, kept besides), so the idle meet in the ones kept. The
ones the AI retired are set going again when the fort grows past a quarter
more than the open ones serve (`per` x open + `per` // 4: no flapping at
the line). Temples only while an open one serves all gods (a temple to one
god retired would leave its worshippers none). Guildhalls, the library and
hospitals are never touched.

Config keys read with defaults (PLANNER_CONFIG is pinned by r7 d6):
`social_places_per` 40, `social_places_on` True.
"""

from __future__ import annotations

import math

from digest import _d, _l
from planner_core import Proposal

__all__ = ["social_places_keep", "social_places_plan", "_social_places_rule"]


def social_places_keep(citizens: int, cfg: dict) -> int:
    """How many taverns (and temples) a fort of `citizens` keeps open."""
    per = max(1, int(cfg.get("social_places_per", 40)))
    return max(1, min(int(cfg.get("social_halls_max", 6)), math.ceil(max(0, citizens) / per)))


def _target(active: int, retired: int, citizens: int, cfg: dict) -> int:
    """The open count wanted of one kind: down to the keep when more are
    open; up (from the AI's retired) when the fort has grown past the open
    ones by a quarter of `per`; else as it is."""
    per = max(1, int(cfg.get("social_places_per", 40)))
    keep = social_places_keep(citizens, cfg)
    if active > keep:
        return keep
    if retired > 0 and citizens > active * per + per // 4:
        return min(active + retired, max(keep, active + 1))
    return active


def social_places_plan(s: dict, cfg: dict) -> dict | None:
    """{taverns, temples, open_taverns, open_temples, retired_taverns,
    retired_temples, citizens} when the open taverns or temples should
    change, else None."""
    loc = _d(s.get("locations"))
    if "locations" in (s.get("_errors") or ()) or loc.get("error"):
        return None
    rec = _d(_d(s.get("society")).get("recreation"))
    if rec.get("error"):
        return None
    citizens = int(_d(s.get("dwarves")).get("total") or 0)
    if citizens <= 0:
        return None
    retired = {x for x in _l(rec.get("retired")) if isinstance(x, int)}
    # the player's (made active again after the AI retired them): kept besides, not counted
    held = {x for x in _l(rec.get("player_kept")) if isinstance(x, int)}
    rows = [e for e in _l(loc.get("list")) if isinstance(e, dict) and _l(e.get("zones"))]
    out = {"citizens": citizens}
    change = False
    for kind, key in (("taverns", "INN_TAVERN"), ("temples", "TEMPLE")):
        mine = [e for e in rows if e.get("type") == key]
        open_ = [e for e in mine if not e.get("inactive") and e.get("id") not in held]
        back = [e for e in mine if e.get("inactive") and e.get("id") in retired]
        out["open_" + kind], out["retired_" + kind] = len(open_), len(back)
        if not open_:
            out[kind] = 1                 # none open: the bridge keeps the best one (or has none)
            change = change or bool(back)
            continue
        t = _target(len(open_), len(back), citizens, cfg)
        # a temple to one god retired leaves its worshippers none: only while an
        # open temple serves all gods (one the bridge keeps first)
        if kind == "temples" and t < len(open_) and not any(e.get("any_deity") for e in open_):
            t = len(open_)
        out[kind] = t
        change = change or t != len(open_)
    return out if change else None


def _social_places_rule(s: dict, cfg: dict, proposals: list | None) -> None:
    if proposals is None or not cfg.get("social_places_on", True):
        return
    p = social_places_plan(s, cfg)
    if p is None:
        return
    bwf = _d(_d(_d(s.get("needs")).get("needs")).get("BeWithFriends"))
    badly = int(bwf.get("badly") or 0)
    per = int(cfg.get("social_places_per", 40))
    shrink = p["taverns"] < p["open_taverns"] or p["temples"] < p["open_temples"]
    if shrink:
        why = (f"{p['open_taverns']} tavern(s) and {p['open_temples']} temple(s) open for {p['citizens']} "
               f"citizens (one of each for every {per} is enough): the idle scatter over them and friends "
               f"seldom meet ({badly} badly miss friends): keep {p['taverns']} tavern(s) and {p['temples']} "
               "temple(s), the best, and make the others' zones inactive (set going again when the fort grows)")
    else:
        why = (f"the fort has grown to {p['citizens']} citizens: {p['taverns']} tavern(s) and {p['temples']} "
               f"temple(s) open again (of those the AI retired; {p['open_taverns']} and {p['open_temples']} open now)")
    proposals.append(Proposal("social_places", {"type": "social_places", "taverns": p["taverns"],
                                                "temples": p["temples"]}, why, 4))
