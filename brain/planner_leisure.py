"""planner_leisure (0.105.82): soldiers short of what only time off gives.

B "Monastery", 23 Nov: 20-34% truly idle civilians kept all four squads on
constant training ("many idle hands": planner_military); 20 of 20 dwarves
missing drink and 13 of 13 merriment were soldiers, 28 miserable, dwarves
strangling dwarves. While a fifth of the soldiers badly miss these, the
squads take turns off instead.
"""

from __future__ import annotations

from digest import _d

__all__ = ["LEISURE_NEEDS", "soldiers_short_of_leisure", "inside_few"]

# (BeWithFriends left out: it wants friends, not time off; 54 of 59 soldiers in happy A miss it)
LEISURE_NEEDS = ("DrinkAlcohol", "MakeMerry", "Socialize", "PrayOrMeditate", "TakeItEasy")


def soldiers_short_of_leisure(s: dict, cfg: dict) -> str:
    """(0.105.82) The leisure need most soldiers badly miss, when at least
    `leisure_starved_soldiers` (3) and `leisure_starved_share` (a fifth) of
    the soldiers do ("" otherwise, or with no per-soldier counts): their
    squads get turns off rather than all training for the idle civilians."""
    needs = _d(_d(s.get("needs")).get("needs"))
    sol = _d(s.get("dwarves")).get("in_squads")
    sol = sol if isinstance(sol, int) and not isinstance(sol, bool) and sol > 0 else 0
    if not sol:
        return ""
    best, n = "", 0
    for k in LEISURE_NEEDS:
        b = _d(needs.get(k)).get("badly_soldiers")
        if isinstance(b, int) and not isinstance(b, bool) and b > n:
            best, n = k, b
    if n >= max(int(cfg.get("leisure_starved_soldiers", 3)), sol * float(cfg.get("leisure_starved_share", 0.2))):
        return best
    return ""




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
