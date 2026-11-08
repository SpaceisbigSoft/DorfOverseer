"""planner_labor: who does what (split out of planner_industry in 0.105.25,
13c): miners, woodcutters and plant gatherers through DF's work details, the
elves' tree quota, jobs nobody takes, the details trimmed, free time for the
friendless. planner_industry re-exports every name here."""

from __future__ import annotations

import math
from quirks import has_rule
from digest import _d, _l
from planner_core import *  # noqa: F401,F403
from planner_farms import drink_below_target, drink_short

__all__ = ["LABOR_MODES_FIXED", "trees_this_year", "_free_time_rule", "_labor_rules", "OWN_LABOR_RULES", "woodcutters", "gatherers", "DEAD_LABORS", "_labor_waiting_rule"]


LABOR_MODES_FIXED = ("EverybodyDoesThis", "NobodyDoesThis")


def trees_this_year(s: dict, memory) -> tuple[int, int | None]:
    """(0.89) Trees felled this game year, and the elves' cap if elves trade
    with the fort (None otherwise: no quota to keep)."""
    dp = _d(s.get("diplomacy"))
    tr, cap = dp.get("trees_removed"), dp.get("tree_cap")
    ty = getattr(memory, "tree_year", None) if memory is not None else None
    felled = 0
    if isinstance(tr, int) and isinstance(ty, dict) and isinstance(ty.get("base"), int) \
            and ty.get("year") == _d(s.get("date")).get("year"):
        felled = max(0, tr - ty["base"])
    if not dp.get("elves") or not isinstance(cap, int) or cap <= 0:
        return felled, None
    return felled, cap


def _free_time_rule(s: dict, citizens: int, cfg: dict, proposals: list, notes: list) -> None:
    """(0.104.10) Time to be with friends: DF's "everybody does this" for
    planting and plant gathering keeps every dwarf on call (Enxah: 3 of 88
    idle, 167 jobs, 44 badly wanting company). While many badly want friends
    and hardly anyone is idle, those details go to a crew (the most skilled:
    one planter a farm plot, 3 to 12; 3 gatherers); once company is no longer
    wanted badly by many, the AI's narrowed details go back to everybody. A
    detail you set yourself is never touched (the bridge checks)."""
    soc = _d(_d(s.get("needs")).get("social"))
    lb = _d(s.get("labor"))
    if not soc or not lb or citizens < cfg["free_time_min_pop"]:
        return
    friends = int(_d(_d(_d(s.get("needs")).get("needs")).get("BeWithFriends")).get("badly") or 0)
    idle_share = int(soc.get("idle") or 0) / max(1, int(soc.get("citizens") or citizens))
    narrowed = lb.get("narrowed") if isinstance(lb.get("narrowed"), dict) else {}
    jobs = _d(lb.get("jobs"))
    if friends >= citizens * cfg["free_time_friends_share"] and idle_share < cfg["free_time_idle_below"]:
        plots = int(_d(s.get("farms")).get("built") or 0)
        for job, keep in (("farming", max(3, min(12, plots))), ("gathering", 3)):
            if job in narrowed or _d(jobs.get(job)).get("mode") != "EverybodyDoesThis":
                continue
            proposals.append(Proposal("free_time", {"type": "narrow_detail", "job": job, "keep": keep},
                                      f"{friends} dwarves badly want time with friends and only "
                                      f"{round(idle_share * 100)}% are ever idle: {job} goes to a crew of {keep} "
                                      "(the most skilled), not everybody", 5))
            return                                              # one a cycle
    elif narrowed and friends < citizens * cfg["free_time_widen_share"]:
        job = sorted(narrowed)[0]
        proposals.append(Proposal("free_time", {"type": "narrow_detail", "job": job, "widen": True},
                                  f"only {friends} dwarves badly want company now: {job} back to everybody", 6))


def _labor_rules(s: dict, citizens: int, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """Who does what (lua/ai-labor.lua): enough miners for the digging while
    picks lie unused; plant gatherers, fishers, farmers and a woodcutter for
    what the fort has to do. Each through the game's own work details; a
    detail you set to everybody or nobody is left alone. Also: shrubs near
    the fort marked for gathering while it has no farm."""
    lb = _d(s.get("labor"))
    jobs = _d(lb.get("jobs"))
    if any(_d(j).get("unsorted") for j in jobs.values()):
        proposals.append(Proposal("labor", {"type": "assign_labor", "job": "mining", "count": 0},
                                  "a work detail's member list is out of order (bridge 0.38.0): put it in order "
                                  "so the game gives everyone their labours again", 1))

    def want(job: str, n: int, why: str, pri: int = 3) -> None:
        j = _d(jobs.get(job))
        if not j or j.get("mode") in LABOR_MODES_FIXED or not j.get("candidates"):
            return
        short = n - int(j.get("doing") or 0)
        if short > 0:
            proposals.append(Proposal("labor", {"type": "assign_labor", "job": job, "count": min(10, short)},
                                      f"{why}: {j.get('doing') or 0} dwarf(s) do it, {n} wanted: put {short} "
                                      f"more on it", pri))

    # miners: the digging waiting, up to the free picks
    dig, need = lb.get("dig") or 0, lb.get("need") or 0
    if dig and need > 0 and (lb.get("candidates") or 0) > 0 and \
            _d(jobs.get("mining")).get("mode") not in LABOR_MODES_FIXED:
        proposals.append(Proposal("labor", {"type": "assign_labor", "job": "mining", "count": min(10, need)},
                                  f"{dig} tile(s) to dig, {lb.get('miners') or 0} dwarf(s) mining and "
                                  f"{lb.get('picks') or 0} pick(s): let {need} more dwarf(s) mine", 2))
    if dig and (lb.get("miners") or 0) == 0 and (lb.get("picks") or 0) == 0:
        why = (f"{lb['soldier_picks']} pick(s) are in soldiers' hands (a uniform with \"any weapon\" takes them)"
               if lb.get("soldier_picks") else "the fort has no pick")
        ask_player(notes, f"{dig} tile(s) wait to be dug and nobody can dig: {why}. Give the squad a uniform "
                          "with a real weapon, or make a pick at a forge")
    elif lb.get("soldier_picks"):
        notes.append(f"{lb['soldier_picks']} pick(s) are in soldiers' hands, so fewer dwarves can dig")

    small = citizens < cfg["young_fort"]
    farms = has_farms(s)
    hungry = food_per_dwarf(s) < cfg["found_food_per_dwarf"]
    # far more gathering waiting than a fed fort needs (old marks): cancelled
    gathering = int(_d(_d(s.get("jobs")).get("by_type")).get("GatherPlants") or 0)
    if not hungry and gathering > cfg["gather_jobs_max"] and food_per_dwarf(s) >= cfg["established_food_per_dwarf"]:
        proposals.append(Proposal("gather_trim", {"type": "trim_gathering", "keep": cfg["gather_jobs_keep"]},
                                  f"{gathering} plant-gathering jobs wait and the fort has "
                                  f"{food_per_dwarf(s):g} food a dwarf: cancel all but {cfg['gather_jobs_keep']} "
                                  "(the farthest first)", 5))
    # while food is short: shrubs gathered (a few at a time: a fort where
    # everybody gathers drops everything else for it), fish caught
    thirsty = drink_short(s, cfg)          # (0.99.6) wild plants and fruit to brew, and their seeds
    if (hungry or thirsty) and (lb.get("shrubs") or 0) > 0 and (lb.get("gather_marked") or 0) < 5:
        n = max(20, min(100, citizens * 4, lb["shrubs"]))
        why = (f"only {food_per_dwarf(s):g} food a dwarf" + ("" if farms else " and no farm yet")
               if hungry else f"only {int(_d(s.get('stocks')).get('drink') or 0)} drink for {citizens} and "
               "little a still can brew")
        proposals.append(Proposal("gather", {"type": "gather_plants", "count": n},
                                  why + f": gather {n} of the {lb['shrubs']} shrub(s) near the fort "
                                  "(food and drink, and seeds)", 2))
    if (lb.get("gather_marked") or 0) > 0 or ((hungry or thirsty) and (lb.get("shrubs") or 0) > 0):
        want("gathering", gatherers(_traits(s) if isinstance(s.get("settings"), dict) else {}, small),
             "shrubs to gather")
    fishers = 0
    if (lb.get("fish_water") or 0) > 0:
        river = 1 if memory is not None and has_rule(memory.culture, "river_bridges") else 0   # (0.103) Riverfolk
        fishers = (1 if citizens < 10 else 2) + river
        want("fishing", fishers, "water to fish in near the fort")
    # (0.104.166) far more fishing than wanted: the rest off the detail. Fishing
    # is long, lonely work at far water (Teacheroar: 84 civilians on it, no fish
    # caught, fisherdwarves the first to break and kill in the tantrum spirals)
    fj = _d(jobs.get("fishing"))
    fdoing = int(fj.get("doing") or 0)
    if fj.get("mode") == "OnlySelectedDoesThis" and fdoing > fishers + cfg["labor_trim_margin"]:
        caught = int(_d(s.get("stocks")).get("raw_fish") or 0) + int(_d(s.get("stocks")).get("fish") or 0)
        proposals.append(Proposal("labor_trim", {"type": "trim_labor", "job": "fishing", "keep": fishers},
                                  f"{fdoing} dwarves are on the fishing detail, {fishers} wanted"
                                  + (" and no fish in store" if not caught else "")
                                  + ": the rest off it (fishing is long work alone at far water; "
                                  "they miss their friends, crafts and prayer)", 3))
    if farms:
        want("farming", 2 if small else max(3, citizens // 10), "farm plots to tend")
    wc = _d(jobs.get("woodcutting"))
    axes = int(wc.get("tools") or 0)
    if axes:
        cutters = woodcutters(_traits(s) if isinstance(s.get("settings"), dict) else {}, small)
        # (0.104.142) more while the wood is under what the fort keeps
        # (Teacheroar: 659 -> 360 logs for 206 dwarves in a season, 1 cutter;
        # the furniture's wooden part and wooden crafts wait on it)
        wood = int(_d(s.get("stocks")).get("wood") or 0)
        short = citizens * cfg["wood_per_dwarf"] - wood
        if short > 0 and not small:
            cutters = min(max(cutters, citizens // cfg["dwarves_per_woodcutter"]),
                          cutters + -(-short // cfg["wood_short_per_cutter"]))
        if memory is not None and has_rule(memory.culture, "elf_friends"):
            # (0.103.4) Elf-friends: one cutter; two while short and well under the elves' quota
            felled, cap_ = trees_this_year(s, memory)
            roomy = cap_ is None or felled < cap_ * cfg["tree_quota_share"] / 2
            cutters = min(cutters, 2 if short > 0 and roomy else 1)
        cutters = min(axes, cutters)
        want("woodcutting", cutters,
             "trees to cut (wood for beds, barrels and bins)"
             + (f"; the wood is {short} short of what the fort keeps" if short > 0 else ""), 4)
    dd = _d(s.get("dead"))
    haunted = int(dd.get("ghosts") or 0) > 0 or int(dd.get("unburied") or 0) > 0     # (0.105.22)
    _labor_waiting_rule(lb, citizens, cfg, proposals, drink_below_target(s, citizens, cfg, memory),   # (0.104.169)
                        haunted)


# Labours with rules of their own (miners by the digging and picks, woodcutters
# by the axes, gatherers, fishers, farmers by the work there)
OWN_LABOR_RULES = {"MINE", "CUTWOOD", "HERBALIST", "FISH", "PLANT"}


def woodcutters(traits: dict, small: bool) -> int:
    """Surface (underground - above ground): woodcutters wanted (axes
    permitting): 1 at -50 or lower, 1-2 between, one more from +50."""
    v = traits.get("surface", 0) or 0
    base = 1 if small else 2
    return 1 if v <= -50 else base + (1 if v >= 50 else 0)


def gatherers(traits: dict, small: bool) -> int:
    """Surface: plant gatherers while shrubs wait: 2-3, one fewer at -50 or
    lower, one more from +50."""
    v = traits.get("surface", 0) or 0
    base = 2 if small else 3
    return max(1, base + (1 if v >= 50 else -1 if v <= -50 else 0))


# (0.105.22) the dead's work: slabs (a mason), their engraving, coffins
DEAD_LABORS = ("MASON", "DETAIL", "STONE_CRAFT")


def _labor_waiting_rule(lb: dict, citizens: int, cfg: dict, proposals: list, thirsty: bool = False,
                        haunted: bool = False) -> None:
    """Work that waits for a worker (lua/ai-labor.lua's waiting_work): a
    labour with jobs nobody has taken while none of its dwarves is free gets
    more dwarves, through the detail that carries it (a few at a time, up to a
    quarter of the fort). And dwarves skilled in a detail's trade who aren't
    on it (migrants come with trades) are put on it."""
    made = 0
    for w in _l(lb.get("waiting")):
        if not isinstance(w, dict) or made >= cfg["labor_moves_per_cycle"]:
            continue
        lab, jobs, holders = str(w.get("labor")), int(w.get("jobs") or 0), int(w.get("holders") or 0)
        # (0.102.2) brewing while drink is short: one waiting job is enough
        # (Monastery: 5 stills, 4 brewers, drink 1.9 -> 0.1 a dwarf)
        # (0.105.22) and the dead's work while ghosts walk or bodies wait: B
        # (4-5 Nov) had 41 ghosts, the slab order's one job waiting at the
        # workshop "for a worker with the labour" 30 times, no mason added
        # (0.105.24) and work nobody in the fort can do at all (no dwarf outside
        # the squads has the labour): one job waits for ever. D and E (2-5 Nov)
        # bound the library's quires one sheet at a time: make_quire "1 job
        # waits at the workshop for a worker with the labour" 60 days, then
        # cancelled as stuck, 140 and 73 times, and the library kept 0 of 10
        # writing materials (parchment in C 51 times, likewise)
        least = 1 if ((thirsty and lab == "BREWER") or (haunted and lab in DEAD_LABORS) or holders == 0) \
            else cfg["labor_waiting_jobs"]
        if (lab in OWN_LABOR_RULES or lab.startswith("HAUL") or jobs < least
                or (w.get("idle") or 0) > 0 or w.get("mode") in LABOR_MODES_FIXED
                or holders >= max(2, citizens // 4)):
            continue
        n = min(3, max(1, math.ceil(jobs / 5)))
        proposals.append(Proposal("labor", {"type": "assign_labor", "job": lab, "count": n},
                                  f"{jobs} {lab.lower().replace('_', ' ')} job(s) wait and none of the {holders} "
                                  f"dwarf(s) who do it is free: put {n} more on it"
                                  + (f" (the {w.get('detail')} work detail)" if w.get("detail") else ""), 4))
        made += 1
    for k in _l(lb.get("skilled_off")):
        if not isinstance(k, dict) or made >= cfg["labor_moves_per_cycle"]:
            continue
        lab, n = str(k.get("labor")), int(k.get("skilled") or 0)
        if lab in ("MINE", "CUTWOOD") or n <= 0:       # (those go by the picks and axes)
            continue
        proposals.append(Proposal("labor", {"type": "assign_labor", "job": lab, "count": min(3, n),
                                            "min_skill": 3},
                                  f"{n} dwarf(s) skilled in {lab.lower().replace('_', ' ')} aren't on the "
                                  f"{k.get('detail')} work detail: put them on their trade", 5))
        made += 1
