"""planner_leisure (0.105.82): soldiers short of what only time off gives.

B "Monastery", 23 Nov: 20-34% truly idle civilians kept all four squads on
constant training ("many idle hands": planner_military); 20 of 20 dwarves
missing drink and 13 of 13 merriment were soldiers, 28 miserable, dwarves
strangling dwarves. While a fifth of the soldiers badly miss these, the
squads take turns off instead.
"""

from __future__ import annotations

from digest import _d

__all__ = ["LEISURE_NEEDS", "COMPANY_NEEDS", "soldiers_short_of_leisure", "friends_counted", "squad_shortage",
           "company_short", "squad_mostly_short", "inside_few"]

# (BeWithFriends left out: it wants friends, not time off; 54 of 59 soldiers in happy A miss it)
# (0.105.97) ...unless the fort is unhappy (friends_counted): B, 23 Nov, 76 of
# 88 badly wanting friends, 37 of them soldiers, 40% unhappy, 29 killed by
# fellow citizens; friends are made where the others are, off duty
LEISURE_NEEDS = ("DrinkAlcohol", "MakeMerry", "Socialize", "PrayOrMeditate", "TakeItEasy")
# (0.105.97) what the recreation burrow gives a soldier off duty: the
# taverns, the temples, the others
COMPANY_NEEDS = ("BeWithFriends", "DrinkAlcohol", "PrayOrMeditate")


# (r6 c2) kept local: a positive count only (0 for none, a bool or a negative)
def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def _soldiers(s: dict) -> int:
    return _int(_d(s.get("dwarves")).get("in_squads"))


def _short_line(s: dict, cfg: dict, sol: int) -> float:
    return max(int(cfg.get("leisure_starved_soldiers", 3)), sol * float(cfg.get("leisure_starved_share", 0.2)))


def friends_counted(s: dict, cfg: dict) -> bool:
    """(0.105.97) Does BeWithFriends count as a soldier's leisure need? Only in
    a fort unhappy past `unhappy_wide_share` (a fifth): happy A had 54 of 59
    soldiers missing friends and nothing wrong; B (40% unhappy) lost 29 to
    fellow citizens."""
    from planner_society import unhappy_wide
    return unhappy_wide(s, cfg)


def soldiers_short_of_leisure(s: dict, cfg: dict) -> str:
    """(0.105.82) The leisure need most soldiers badly miss, when at least
    `leisure_starved_soldiers` (3) and `leisure_starved_share` (a fifth) of
    the soldiers do ("" otherwise, or with no per-soldier counts): their
    squads get turns off rather than all training for the idle civilians."""
    needs = _d(_d(s.get("needs")).get("needs"))
    sol = _soldiers(s)
    if not sol:
        return ""
    best, n = "", 0
    for k in LEISURE_NEEDS:
        b = _d(needs.get(k)).get("badly_soldiers")
        if isinstance(b, int) and not isinstance(b, bool) and b > n:
            best, n = k, b
    if n >= _short_line(s, cfg, sol):
        best_ok = best
    else:
        best_ok = ""
    # (0.105.97) friends too, in an unhappy fort, from their own share
    # (`leisure_friends_share`, a third of the soldiers)
    f = _int(_d(needs.get("BeWithFriends")).get("badly_soldiers"))
    if (f > (n if best_ok else 0) and f >= max(int(cfg.get("leisure_starved_soldiers", 3)),
                                               sol * float(cfg.get("leisure_friends_share", 1 / 3)))
            and friends_counted(s, cfg)):
        return "BeWithFriends"
    return best_ok


def squad_shortage(s: dict) -> dict:
    """(0.105.97) Each squad's members and how many badly miss friends, drink
    or prayer (`short`) and drink or prayer alone (`short_np`): the bridge's
    society.recreation.squads ({} from an older bridge). Keys are squad ids."""
    out = {}
    for k, v in _d(_d(_d(s.get("society")).get("recreation")).get("squads")).items():
        v = _d(v)
        try:
            out[int(k)] = {"n": _int(v.get("n")), "short": _int(v.get("short")), "short_np": _int(v.get("short_np"))}
        except (TypeError, ValueError):
            continue
    return out


def company_short(s: dict, cfg: dict) -> int:
    """(0.105.97) The soldiers badly missing friends, drink or prayer (friends
    only while friends_counted) when they are `leisure_starved_soldiers` (3)
    and `leisure_starved_share` (a fifth) of the soldiers, else 0. From the
    squads' own counts when the bridge gives them (one soldier counted once),
    else the most missing any one of those needs. While it is nonzero, at most
    half the squads train at a time, a squad most of whom are short rests a
    turn more, and off-duty soldiers get places in the recreation burrow."""
    sol = _soldiers(s)
    if not sol:
        return 0
    friends = friends_counted(s, cfg)
    sq = squad_shortage(s)
    if sq:
        n = sum(r["short"] if friends else r["short_np"] for r in sq.values())
    else:
        needs = _d(_d(s.get("needs")).get("needs"))
        n = max([_int(_d(needs.get(k)).get("badly_soldiers")) for k in COMPANY_NEEDS
                 if friends or k != "BeWithFriends"] or [0])
    return n if n >= _short_line(s, cfg, sol) else 0


def squad_mostly_short(s: dict, cfg: dict, sid) -> bool:
    """(0.105.97) Do most of squad `sid`'s members badly miss friends (while
    counted), drink or prayer? False without the bridge's squad counts."""
    r = squad_shortage(s).get(sid)
    if not r or not r["n"]:
        return False
    return 2 * (r["short"] if friends_counted(s, cfg) else r["short_np"]) > r["n"]




def inside_few(s: dict, cfg: dict, reach: list, threats: dict) -> list:
    """(0.105.83) The ids of the enemies in reach when they are a few
    (`inside_defence_max`, 6) and every one is already inside the fort (the
    gate scan's intruders_inside, the hunt's "inside" targets, thieves and
    interrupters inside: planner_holdfast._inside_ids), fliers and wild
    animals included, none a great danger, fire breather or building
    destroyer; [] otherwise. One squad goes at them whatever the Rules tab
    says (B's ravens, 23 Nov)."""
    from planner_holdfast import _inside_ids
    ids = [i for i in reach if i is not None]
    if not ids or len(ids) > int(cfg.get("inside_defence_max", 6)):
        return []
    inside = _inside_ids(s)
    for i in ids:
        t = threats.get(i)
        if (not isinstance(t, dict) or i not in inside or t.get("great_danger") or t.get("destroyer")
                or t.get("fire_breather")):
            return []
    return ids
