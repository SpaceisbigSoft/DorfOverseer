"""planner_squad_trim: soldiers back to civilian life when the army is bigger
than the fort wants (item8, the player, 26 Nov: "Trim to its slider").

E (Deep mine, Militarism 0: the slider asks 10% of the citizens) kept 39
soldiers in 4 squads of ~100 citizens (~42% of the adults), its soldiers the
fort's most unmet (19 badly missing friends, a drink or prayer). Three
things held it there: the defence floor kept the third of the adults for two
years after a forgotten beast had gone (planner_defence_floor: the cap now
eases to the slider's share once the map is quiet), Goblin-haunted's quarter
more was put on top of the floor (31 made 39: now on the slider's number
alone), and the trim never ran while 5+ civilians badly wanted to train (14
in E): the fill could only ever add.

The trim (lua/ai-military-draft.lua trim: the unhappiest and those badly
missing friends, a drink or prayer first, then the least skilled at arms;
never a squad leader, one who longs to fight, a squad out on orders or the
training squad):
- begins once the soldiers are more than `trim_margin_min` (or
  `trim_margin_share` of the wanted number) over it, and once begun (a trim
  in the last `trim_continue_days`) goes on down to the wanted number, which
  is never below the defence floor nor the guard of 3 (soldiers_wanted);
- never while a real threat is on the map (one that can reach the dwarves,
  an invader, or a great danger that can reach them: the defence floor's
  `real`; a beast sealed in the caverns doesn't hold it for years), a dwarf is berserk, a
  fight is under way (memory.fight, `fight_freeze_days`) or the keen lift is
  held (a crisis: the wanted number is raised for the keen on purpose);
- at most `max_trim_per_cycle` a time, `trim_week_max` a week and a squad's
  worth (`trim_season_max`) a season (memory.trimmed, written by
  planner_record).
"""

from __future__ import annotations

from digest import _d
from planner_core import TICKS_PER_DAY, abs_tick

__all__ = ["trim_plan", "trimmed_since"]


def trimmed_since(memory, now: int, days: float) -> int:
    """Soldiers the trim sent home in the last `days` (memory.trimmed)."""
    tr = _d(getattr(memory, "trimmed", None)) if memory is not None else {}
    return sum(1 for t in tr.values() if isinstance(t, int) and 0 <= now - t < days * TICKS_PER_DAY)


def _held_keen_lift(s: dict, memory, cfg: dict) -> bool:
    kl = _d(getattr(memory, "keen_lift", None)) if memory is not None else {}
    t = kl.get("tick")
    return (int(kl.get("n") or 0) > 0 and isinstance(t, int)
            and 0 <= abs_tick(s) - t < cfg["keen_lift_days"] * TICKS_PER_DAY)


def trim_plan(s: dict, memory, cfg: dict, have: int, want: int, floor_: dict | None,
              any_reach: bool, berserk_now: bool) -> dict:
    """{count, why} to send `count` soldiers home now; {note} when the army is
    over the wanted number but none go now (said); {} when nothing is to say."""
    over = have - want
    if over <= 0:
        return {}
    now = abs_tick(s)
    margin = max(cfg["trim_margin_min"], round(want * cfg["trim_margin_share"]))
    begun = trimmed_since(memory, now, cfg.get("trim_continue_days", 28)) > 0
    if over <= margin and not begun:
        return {}
    f = _d(floor_)
    if any_reach or float(f.get("real") or 0) > 0:
        return {"note": "a threat is on the map: no soldier goes home until it is gone"}
    if berserk_now:
        return {"note": "a dwarf is berserk: no soldier goes home meanwhile"}
    fight = getattr(memory, "fight", None) if memory is not None else None
    if (isinstance(fight, dict) and fight
            and 0 <= now - int(fight.get("tick") or 0) < cfg["fight_freeze_days"] * TICKS_PER_DAY):
        return {"note": "a fight is under way: the extra soldiers go home once it is over"}
    if _held_keen_lift(s, memory, cfg):
        return {}     # (0.104.168) the keen lift raised the wanted number on purpose; said by the fill
    season_max = int(cfg.get("trim_season_max", 10))
    days = float(cfg.get("trim_season_days", 84))
    season = trimmed_since(memory, now, days)
    week = trimmed_since(memory, now, 7)
    left = min(season_max - season, int(cfg.get("trim_week_max", 3)) - week)
    if left <= 0:
        if season >= season_max:
            return {"note": f"{season} sent home this season already (a squad's worth at most): the rest go "
                            "later in the year"}
        return {"note": f"{week} sent home this week already: a few more next week"}
    count = min(over, int(cfg["max_trim_per_cycle"]), left)
    return {"count": count, "why": f"{season + count} of at most {season_max} this season"}
