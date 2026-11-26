"""(item4) Work for idle miners: exploratory mining for ore and gems, and the
vein rule's pace by the Mining slider.

Why (25-26 Nov, region4): D, the Hermit hold (Mining 0), stood 25-35% idle
for four seasons with 12 miners, 17 picks and `labor.dig` 0: nothing was
marked to dig. Its plan was dug out (Growth -60 asks for no new homes), the
quarry comes only while stone is short (61 usable boulders), and the vein
rule (planner_industry_stone._industry_rules) mines only while bars are
under 50 x factor and dug ore under ore_stock_max (30 x factor): D had 73
bars and 257 ore boulders. E, the Deep mine (Mining 150, factor 2.83), had
the fewest ore boulders of the six (54) though its bars (78) were under its
line (141): the vein rule also waits for fewer than 50 tiles of digging,
and E's plan always had 150-300 waiting, so it mined three veins in a day
and then none.

Here:
  * `vein_dig_cap`: the digging a vein waits for, by the miners and Mining
    (vein_dig_per_miner tiles a miner x factor, never under the old 50):
    E's 20 miners at x2.83 take a vein with up to 282 tiles waiting, D's 12
    at x1 with 60, F's 20 at x0.66 with 66;
  * `ore_paced`: the vein rule's own pace, ore_days / factor (E every 2.5
    days, D a week, F 10.6 days; the select cooldown `ore_cooldown_ticks` is
    the floor under it);
  * `_prospect_rule` (rule `prospect`): miners with little to dig (under
    prospect_dig_per_miner tiles a miner x factor) and Mining over -50 (the
    Garden fort's -60 never) dig a vein for its own sake, every
    prospect_days / factor (D every 3 days, E every day): an ore while the dug ore is under the Mining
    line (the metal least in store first), else gems while the rough gems
    are under prospect_gems_below x factor. The bridge's mine_ore (lua/
    ai-industry.lua) takes metal 'GEM' for any gem's vein; it follows a vein
    uncovered beside the fort or drives a drift of at most 30 tiles to a
    hidden one, only through rock that is dry, cool, roofed, out of every
    cavern and aquifer, and clear of the AI's levels, rooms and the dig
    guard's adamantine. A metal or gems refused waits out the usual
    refusal back-off (the metal is in the refusal key); nothing while a
    threat can reach the dwarves or the fort is young.

(r34a) E, the Deep mine (26 Nov, 0.105.129): 26-27 miners, 0 tiles to dig,
idle 32-36%: `prospect` refused "no vein within 30 tiles" every time (the
bridge's drift search was starved: see find_drift in lua/ai-industry.lua)
and nothing else gave the miners work (the Mining slider asks no levels
beyond the fort's needs, and E's plan was dug out). Here:
  * `_explore_rule` (rule `explore`): the same idle miners, when no vein
    is to be had this cycle (none proposed: exploratory mining refused and
    waiting out its back-off, or ore and gems enough in store), dig
    exploratory tunnels (the bridge's explore_dig): straight 1-wide tunnels
    from the dwarves' ground into unseen rock, away from the levels, one
    miner each (explore_per_tunnel_miners a tunnel, at most 6; none with
    fewer idle miners than that), going on
    from the last tunnels' ends; they uncover veins for the vein rule and
    prospect, and leave a boulder about every fourth tile for the masons.
    explore_tiles x factor tiles (10-80), every explore_days / factor (a day
    at least); the reason says why no vein instead.
"""

from __future__ import annotations

from digest import _d
from planner_core import Proposal, TICKS_PER_DAY, _refused_wait, _traits, abs_tick, factor, mining_plan, young_fort
from planner_deep import is_adamantine

__all__ = ["vein_dig_cap", "ore_paced", "prospect_target", "_prospect_rule", "explore_size", "_explore_rule"]


def _mf(s: dict) -> float:
    return factor(_traits(s) if isinstance(s.get("settings"), dict) else {}, "mining")


def vein_dig_cap(s: dict, cfg: dict) -> int:
    """Tiles of digging waiting under which a vein is mined (the miners and Mining)."""
    miners = int(_d(s.get("labor")).get("miners") or 0)
    return max(int(cfg.get("vein_when_dig_below", 50)), int(miners * cfg.get("vein_dig_per_miner", 5) * _mf(s)))


def _paced(memory, key: str, days: float, now: int) -> bool:
    last = (getattr(memory, "last_fired", None) or {}).get(key) if memory is not None else None
    if not isinstance(last, int) or isinstance(last, bool):
        return True
    gap = max(1.0, days) * TICKS_PER_DAY
    return not 0 <= now - last < gap


def ore_paced(s: dict, memory, cfg: dict) -> bool:
    """The vein rule's pace: a vein every ore_days / factor(Mining) days at most."""
    return _paced(memory, "ore", cfg.get("ore_days", 7) / _mf(s), abs_tick(s))


def _ore_by_metal(s: dict) -> dict:
    out: dict = {}
    for v in _d(_d(s.get("industry")).get("ore_stock_by")).values():
        if isinstance(v, dict):
            for m in v.get("metals") or []:
                if isinstance(m, str):
                    out[m] = out.get(m, 0) + int(v.get("n") or 0)
    return out


def prospect_target(s: dict, memory, cfg: dict) -> tuple[str, str] | None:
    """(metal or 'GEM', why) for the next exploratory vein, or None."""
    ind = _d(s.get("industry"))
    mp = mining_plan(_traits(s), cfg)
    now = abs_tick(s)

    def free(metal: str) -> bool:
        if memory is None:
            return True
        p = Proposal("prospect", {"type": "mine_ore", "metal": metal}, "", 5)
        return _refused_wait(memory, p, now) is None
    stock = int(ind.get("ore_stock") or 0)
    if stock < mp["ore_stock_max"]:
        have = _ore_by_metal(s)
        ores = [(m, _d(v)) for m, v in _d(ind.get("ores")).items()
                if isinstance(m, str) and isinstance(v, dict) and int(v.get("tiles") or 0) > 0
                and not is_adamantine(m) and not is_adamantine(v.get("ore"))]
        ores.sort(key=lambda mv: (have.get(mv[0], 0), -int(mv[1].get("tiles") or 0), mv[0]))
        for m, v in ores:
            if free(m):
                return m, (f"{stock} ore boulders in store (the Mining line {mp['ore_stock_max']}), "
                           f"{have.get(m, 0)} of {m.lower()}")
    gems = int(_d(s.get("stocks")).get("rough_gems") or 0)
    want = int(cfg.get("prospect_gems_below", 20) * _mf(s))
    if gems < want and free("GEM"):
        return "GEM", f"{gems} rough gems in store (under {want})"
    return None


def _prospect_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """Idle miners with nothing to dig: a vein of ore or gems, by the Mining slider."""
    if not isinstance(s.get("settings"), dict) or memory is None:
        return
    traits = _traits(s)
    if not mining_plan(traits, cfg)["veins"] or young_fort(s, cfg):
        return
    lb = _d(s.get("labor"))
    miners, dig = int(lb.get("miners") or 0), int(lb.get("dig") or 0)
    f = factor(traits, "mining")
    if miners <= 0 or dig >= max(1, int(miners * cfg.get("prospect_dig_per_miner", 2) * f)):
        return
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return
    if any(isinstance(p.action, dict) and p.action.get("type") == "mine_ore" for p in proposals):
        return          # the vein rule's own this cycle
    if not _paced(memory, "prospect", cfg.get("prospect_days", 3) / f, abs_tick(s)):
        return
    t = prospect_target(s, memory, cfg)
    if t is None:
        return          # ore and gems in store enough for the fort's Mining (quiet: no note every cycle)
    metal, why = t
    n = max(10, min(80, int(cfg.get("prospect_tiles", 30) * f)))
    what = "a gem vein" if metal == "GEM" else f"a vein of {metal.lower()} ore"
    proposals.append(Proposal(
        "prospect", {"type": "mine_ore", "metal": metal, "count": n, "prospect": True},
        f"{miners} miners with only {dig} tiles to dig and {why}: exploratory mining, {what} "
        f"({n} tiles) through safe rock near the fort", 6))


# --- (r34a) exploratory tunnels: the idle miners' fallback ----------------------------

DIG_TYPES = ("mine_ore", "quarry", "explore_dig")


def _idle_miners(s: dict, cfg: dict) -> tuple[int, int, float] | None:
    """(miners, tiles to dig, Mining factor) when the miners have little to
    dig (prospect's test), the fort may mine veins and isn't young, and no
    threat can reach the dwarves; else None."""
    if not isinstance(s.get("settings"), dict):
        return None
    traits = _traits(s)
    if not mining_plan(traits, cfg)["veins"] or young_fort(s, cfg):
        return None
    lb = _d(s.get("labor"))
    miners, dig = int(lb.get("miners") or 0), int(lb.get("dig") or 0)
    f = factor(traits, "mining")
    if miners <= 0 or dig >= max(1, int(miners * cfg.get("prospect_dig_per_miner", 2) * f)):
        return None
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return None
    return miners, dig, f


def explore_size(miners: int, f: float, cfg: dict) -> tuple[int, int]:
    """(tiles, tunnels) for one call: explore_tiles x factor (10-80), one
    tunnel for each explore_per_tunnel_miners miners (1-6: a tunnel is dug
    one face at a time)."""
    n = max(10, min(80, int(cfg.get("explore_tiles", 24) * f)))
    t = max(1, min(6, miners // max(1, int(cfg.get("explore_per_tunnel_miners", 5)))))
    return n, t


def _no_vein_why(s: dict, memory, cfg: dict) -> str:
    """Why no vein this cycle, in words."""
    now = abs_tick(s)
    p = Proposal("prospect", {"type": "mine_ore", "metal": "GEM"}, "", 5)
    w = _refused_wait(memory, p, now)
    if w is not None:
        return f"no vein to follow (exploratory mining found none in reach; tried again in {w} day(s))"
    if prospect_target(s, memory, cfg) is None:
        return "ore and gems enough in store for the fort's Mining"
    return "exploratory mining's last vein already given (the next when its pace allows)"


def _explore_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(r34a) Idle miners with no vein to dig: exploratory tunnels, by the Mining slider."""
    if memory is None:
        return
    idle = _idle_miners(s, cfg)
    if idle is None:
        return
    miners, dig, f = idle
    if miners < int(cfg.get("explore_per_tunnel_miners", 5)):
        return          # a few miners idle a while: not worth tunnels (a tunnel is one miner's work)
    if any(isinstance(p.action, dict) and p.action.get("type") in DIG_TYPES for p in proposals):
        return          # a vein or a quarry this cycle: that's the miners' work
    if not _paced(memory, "explore", cfg.get("explore_days", 1) / f, abs_tick(s)):
        return
    n, t = explore_size(miners, f, cfg)
    proposals.append(Proposal(
        "explore", {"type": "explore_dig", "count": n, "tunnels": t},
        f"{miners} miners with only {dig} tiles to dig and {_no_vein_why(s, memory, cfg)}: "
        f"{t} exploratory tunnel(s), {n} tiles in all, into unseen safe rock away from the levels "
        "(they uncover veins; about one tile in four leaves a boulder for the masons)", 6))
