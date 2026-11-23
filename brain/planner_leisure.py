"""planner_leisure (0.105.82): soldiers short of what only time off gives.

B "Monastery", 23 Nov: 20-34% truly idle civilians kept all four squads on
constant training ("many idle hands": planner_military); 20 of 20 dwarves
missing drink and 13 of 13 merriment were soldiers, 28 miserable, dwarves
strangling dwarves. While a fifth of the soldiers badly miss these, the
squads take turns off instead.
"""

from __future__ import annotations

from digest import _d

__all__ = ["LEISURE_NEEDS", "soldiers_short_of_leisure"]

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


