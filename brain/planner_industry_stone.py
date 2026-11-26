"""planner_industry_stone: stone, ore, metal and the furnaces (the quarry,
coal, picks, the industry shops, steel, smelting, the kiln and glass)
(split out of planner_industry in r7 d4, moved unchanged).
planner_industry re-exports every name here."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from culture import layout_style, new_history, pick_stone, profile_from, stone_for
from learning import held_levels
import customs
import masterplan
import phases
from planner_food import food_containers_want  # (0.105.40b, M6)
from quirks import has_rule
from digest import _d, _l, normalize
from planner_core import *  # noqa: F401,F403
from planner_orders import *  # noqa: F401,F403  (13c: split out by theme)
from planner_trade import *  # noqa: F401,F403  (13c: split out by theme)
from planner_labor import *  # noqa: F401,F403  (13c: split out by theme)
from planner_farms import *  # noqa: F401,F403  (13c: split out by theme)

__all__ = ["GEAR_ORDER_METALS", "_kiln_rules", "INDUSTRY_SHOPS", "_industry_rules", "_steel_rule", "COAL_STONES", "_coal_rule", "_picks_order", "PRECIOUS_ORES", "stone_crisis", "quarry_size", "_quarry_stock", "_quarry_status", "note_quarry", "quarry_wait", "note_quarry_dug", "_stone_rule", "_glass_rule", "_smelting_rule"]
# ore worth mining for gear, most wanted first (iron makes steel; tin with copper makes bronze)
GEAR_ORDER_METALS = ("IRON", "COPPER", "TIN", "BISMUTH", "SILVER")


def _kiln_rules(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.86) What a kiln makes (DF's reaction_other raws, read from the game):
    plaster powder for the hospital's casts (a gypsum boulder and an empty
    bag, with fuel) and the library's writing materials, one step a cycle:
    quicklime (a calcium carbonate boulder, a bag, fuel) at the kiln -> milk
    of lime (quicklime and an empty bucket) at the ashery -> parchment (a
    fresh hide and milk of lime) at the tanner's -> a blank quire (a sheet)
    at a Craftsdwarf's workshop. A kiln and a tanner's are built when
    missing and there is stone for them. Tanners take fresh hides for
    leather by themselves, so parchment only gets what they leave."""
    sup = _d(s.get("supplies"))
    if "gypsum" not in sup or young_fort(s, cfg):
        return
    b = s["buildings"]
    hosp, lib = _location(s, "HOSPITAL"), _location(s, "LIBRARY")
    powder_short = _location_short(hosp, ("powder",)).get("powder") if hosp else None
    paper_short = _location_short(lib, ("paper",)).get("paper") if lib else None
    need_plaster = bool(powder_short) and (sup.get("plaster") or 0) == 0 and (sup.get("gypsum") or 0) > 0
    need_paper = bool(paper_short) and (sup.get("blank_quires") or 0) < paper_short[1] - paper_short[0]
    if not (need_plaster or need_paper):
        return
    chain = ("make_plaster_powder", "make_quicklime", "make_milk_of_lime", "make_parchment", "make_quire")
    if any(queued(s, {r}) for r in chain):
        return
    bags, buckets, fuel = int(sup.get("empty_bags") or 0), int(sup.get("buckets") or 0), int(sup.get("fuel") or 0)
    missing = []
    if not _has_shop(b, "Kiln") and (need_plaster or (sup.get("calcium_carbonate") or 0) > 0):
        missing.append("Kiln")
    if need_paper and not _has_shop(b, "Tanners") and (sup.get("calcium_carbonate") or 0) > 0:
        missing.append("Tanners")
    if missing:
        open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
        if not _workshops_busy(open_):
            why = []
            if need_plaster:
                why.append(f"plaster powder for the hospital ({sup.get('gypsum')} gypsum boulders)")
            if need_paper:
                why.append("writing materials for the library")
            proposals.append(Proposal("kiln", {"type": "start_project", "kind": "workshops", "shops": missing},
                                      f"{' and '.join(why)}: build {', '.join(missing)}", 6))
        return
    step = None
    if need_plaster and _has_shop(b, "Kiln"):
        if bags and fuel:
            step = ("make_plaster_powder", 1, f"the hospital has {powder_short[0]} of {powder_short[1]} plaster "
                                               f"powder for casts: burn a gypsum boulder into plaster")
        else:
            notes.append(f"plaster for the hospital waits for an empty bag ({bags}) and fuel ({fuel})")
    if step is None and need_paper:
        short = paper_short[1] - paper_short[0] - (sup.get("blank_quires") or 0)
        sheets, milk, hides = int(sup.get("sheets") or 0), int(sup.get("milk_of_lime") or 0), int(sup.get("hides") or 0)
        lime, caco3 = int(sup.get("quicklime") or 0), int(sup.get("calcium_carbonate") or 0)
        # (item5) only the sheets a quire job can reach: those left in the
        # screw press (no pile taking sheets) stalled every make_quire order
        from planner_paper import sheet_stall, sheets_usable
        stall = sheet_stall(s) if sheets else None
        sheets = sheets_usable(s) if sheets else 0
        if stall and not sheets:
            notes.append(f"the library's quires wait: {stall}")
            return
        if sheets and _has_shop(b, "Craftsdwarfs"):
            step = ("make_quire", min(sheets, short, 5), f"the library has {paper_short[0]} of {paper_short[1]} "
                                                          f"writing materials: bind {min(sheets, short, 5)} sheet(s) into quires")
        elif milk and hides and _has_shop(b, "Tanners"):
            step = ("make_parchment", min(milk, hides, short, 5), "parchment for the library from fresh hides")
        elif milk and not hides:
            notes.append("parchment for the library waits for a fresh hide (the tanners take them for leather)")
        elif lime and buckets and _has_shop(b, "Ashery"):
            step = ("make_milk_of_lime", min(lime, short, 3), "milk of lime (for parchment) from quicklime")
        elif caco3 and bags and fuel and _has_shop(b, "Kiln"):
            step = ("make_quicklime", min(caco3, short, 3), "quicklime (for parchment) from limestone")
        elif not caco3:
            notes.append("no limestone, marble, chalk or dolomite boulders for quicklime: the library's paper "
                         "comes from plants instead (a quern and a screw press: planner_paper)")
        elif not bags:
            notes.append("quicklime for the library's paper waits for an empty bag")
    if step:
        recipe, amount, what = step
        proposals.append(Proposal("kiln", {"type": "work_order", "recipe": recipe, "amount": max(1, amount)},
                                  what, 5, True))


INDUSTRY_SHOPS = ["WoodFurnace", "Smelter", "MetalsmithsForge"]


def _industry_rules(s: dict, memory, cfg: dict, citizens: int, proposals: list, notes: list) -> None:
    """Metal: once ore is uncovered near the fort, the furnaces and forge;
    a vein of the most wanted metal mined while bars run low; charcoal for
    the smelter. Smelting itself is DFHack's smelting orders (_smelting_rule)."""
    ores = {k: v for k, v in _d(_d(s.get("industry")).get("ores")).items() if isinstance(v, dict)}
    if not ores or young_fort(s, cfg) and not has_farms(s):
        return
    b = s["buildings"]
    missing = [w for w in INDUSTRY_SHOPS if not _has_shop(b, w)]
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    if missing and not _workshops_busy(open_):
        best = next((m for m in GEAR_ORDER_METALS if m in ores), next(iter(ores)))
        proposals.append(Proposal("industry", {"type": "start_project", "kind": "workshops", "shops": missing},
                                  f"{ores[best]['tiles']} tiles of {best.lower()} ore uncovered near the fort: "
                                  f"dig and build {', '.join(missing)} to turn it into metal", 5))
    bars = _d(_d(_d(s.get("military")).get("gear")).get("bars"))
    total = sum(v for v in bars.values() if isinstance(v, (int, float)))
    lb = _d(s.get("labor"))
    stock = _d(s.get("industry")).get("ore_stock") or 0
    mp = mining_plan(_traits(s) if isinstance(s.get("settings"), dict) else {}, cfg)   # (0.96) Mining
    if (mp["veins"] and total < mp["bars_below"] and (lb.get("dig") or 0) < 50 and (lb.get("miners") or 0) > 0
            and stock < mp["ore_stock_max"]):
        # (0.105.40 M7) a fort without iron: tin for bronze once copper is in hand
        from planner_alloys import tin_ore_first
        metal = tin_ore_first(s, cfg, ores) or next((m for m in GEAR_ORDER_METALS if m in ores), None)
        if metal:
            proposals.append(Proposal("ore", {"type": "mine_ore", "metal": metal, "count": mp["vein_tiles"]},
                                      f"only {total} bars of weapon-grade metal and {ores[metal]['tiles']} tiles of "
                                      f"{metal.lower()} ore uncovered: mine the vein", 5))
    elif not mp["veins"] and total < cfg["smelt_when_bars_below"]:
        notes.append(f"only {total} bars of weapon-grade metal, but Mining is low: no vein mined (metal by trade)")
    su, st = _d(s.get("supplies")), _d(s.get("stocks"))
    furnaces = _d(b.get("furnaces"))
    # Coke from coal first (bituminous coal 9 bars, lignite 5, one fuel a job):
    # far more fuel than charcoal, and no wood burnt
    coal = sorted(((int(_d(v).get("n") or 0), k) for k, v in _d(_d(s.get("stone_use")).get("economic")).items()
                   if k in COAL_STONES and int(_d(v).get("n") or 0) > 0), reverse=True)
    coke_made = False
    # (0.100.1, review) waiting coke orders go only at twice the threshold:
    # at 39/40 fuel they were ordered and cancelled by turns
    if (su.get("fuel") or 0) >= 2 * cfg["coke_when_fuel_below"]:
        # fuel enough: the AI's coke orders still waiting go (0.54 piled a dozen
        # on the one smelter, ahead of pig iron and steel)
        waiting = [o for o in _l(s.get("orders")) if isinstance(o, dict) and o.get("by_ai")
                   and o.get("recipe") in COAL_STONES.values() and (o.get("amount_left") or 0) > 0]
        if waiting:
            proposals.append(Proposal("fuel_trim", {"type": "cancel_work_order", "order_id": waiting[0]["id"]},
                                      f"{su.get('fuel')} charcoal and coke in stock and {len(waiting)} coke order(s) "
                                      "still waiting: cancel one (the smelter has other work)", 5))
    if (furnaces.get("Smelter") and "fuel" in su and 0 < (su.get("fuel") or 0) < cfg["coke_when_fuel_below"]
            and coal and not queued(s, set(COAL_STONES.values()), ai_only=True)):
        n, k = coal[0]
        amount = max(1, min(n, cfg["coke_batch"], (su.get("fuel") or 0)))
        p = Proposal("fuel", {"type": "work_order", "recipe": COAL_STONES[k], "amount": amount},
                     f"only {su.get('fuel') or 0} charcoal or coke and {n} {k.lower().replace('_', ' ')} "
                     f"dug: make coke from {amount}", 4, True)
        # refused (a game without that reaction): charcoal meanwhile
        if memory is None or _refused_wait(memory, p, abs_tick(s)) is None:
            proposals.append(p)
            coke_made = True
    # (0.105.113 item13) while a crafting mood waits on a bar, one log is enough (one charcoal a
    # log, one charcoal a bar): D, 22-24 Nov, 19 logs (under the 20 asked) and eight bar moods mad.
    # The logs counted are those a dwarf can walk to (supplies.wood_reach; an older bridge: all)
    from planner_moods import mood_wants_bar, reach_wood
    bar_mood = mood_wants_bar(s)
    wood = reach_wood(s)
    if (furnaces.get("Smelter") and "fuel" in su and (su.get("fuel") or 0) < cfg["fuel_min"] and not coke_made
            and wood >= (1 if bar_mood else 20) and furnaces.get("WoodFurnace") and not queued(s, {"make_charcoal"})):
        n = min(10, wood) if bar_mood else 10
        proposals.append(Proposal("fuel", {"type": "work_order", "recipe": "make_charcoal", "amount": n},
                                  f"only {su.get('fuel') or 0} charcoal or coke for the smelter"
                                  + (f" and a strange mood waits on a bar: burn {n} of the {wood} log(s) a dwarf "
                                     "can reach" if bar_mood else ": burn some wood"), 3 if bar_mood else 5, True))
    # Smelting: the AI's own orders, one ore stone and one charcoal a bar.
    # DFHack's smelting library (imported since 0.42) only smelts with 100
    # charcoal in stock: region2 sat on 89 ore and 15 charcoal for a season.
    by_ore = {k: v for k, v in _d(_d(s.get("industry")).get("ore_stock_by")).items() if isinstance(v, dict)}
    fuel = su.get("fuel") or 0
    # (0.97) the Rules switch "Smelt ore when metal runs low" (it was DFHack's
    # smelting library only, which current bridges no longer use)
    # (0.104.96) a magma smelter needs no fuel
    magma = bool(furnaces.get("MagmaSmelter"))
    if ((furnaces.get("Smelter") or magma) and by_ore and (fuel > 0 or magma) and total < cfg["smelt_when_bars_below"]
            and player_rules(s)["import_smelting"] and not queued(s, {"smelt_ore"}, ai_only=True)):
        def rank(item):
            ore, v = item
            metals = [m for m in _l(v.get("metals")) if isinstance(m, str)]
            order = min((GEAR_ORDER_METALS.index(m) for m in metals if m in GEAR_ORDER_METALS), default=99)
            return (order, -int(v.get("n") or 0), ore)
        ore, v = min(by_ore.items(), key=rank)
        amount = max(1, min(int(v.get("n") or 0), fuel if not magma else 99, cfg["smelt_batch"]))
        metals = ", ".join(m.lower() for m in _l(v.get("metals")))
        proposals.append(Proposal("smelt", {"type": "work_order", "recipe": "smelt_ore", "amount": amount,
                                            "material": f"INORGANIC:{ore}"},
                                  f"{v.get('n')} {ore.lower()} ore waiting and only {total} bars of weapon-grade "
                                  f"metal: smelt {amount} into {metals}", 4, True))
    _steel_rule(s, cfg, bars, furnaces, fuel, proposals, notes)


def _steel_rule(s: dict, cfg: dict, bars: dict, furnaces: dict, fuel: int, proposals: list, notes: list) -> None:
    """Steel, the best gear metal, from iron in two steps at the smelter:
    pig iron (an iron bar, flux stone, fuel), then steel (a pig iron bar, an
    iron bar, flux, fuel: two steel bars). Some iron is always kept back
    for gear made now; steel is made while there's less than the gear wants."""
    gear = _d(_d(s.get("military")).get("gear"))
    flux = int(_d(s.get("industry")).get("flux_stock") or 0)
    iron, pig, steel = int(bars.get("IRON") or 0), int(gear.get("pig_iron") or 0), int(bars.get("STEEL") or 0)
    magma = bool(furnaces.get("MagmaSmelter"))     # (0.104.96) no fuel needed there
    if not (furnaces.get("Smelter") or magma) or not player_rules(s)["make_gear"] or steel >= cfg["steel_want"]:
        return
    if queued(s, {"pig_iron", "steel"}, ai_only=True):
        return
    spare_iron = iron - cfg["iron_keep"]
    if spare_iron <= 0 or (fuel <= 0 and not magma):
        return
    if flux <= 0:
        if iron >= cfg["iron_keep"] + 4:
            notes.append(f"{iron} iron bars and no flux stone (limestone, dolomite, marble, chalk, calcite) "
                         "dug: no steel until some is")
        return
    if pig < 1:
        n = max(1, min(spare_iron // 2, flux, fuel if not magma else 99, cfg["steel_batch"]))
        proposals.append(Proposal("steel", {"type": "work_order", "recipe": "pig_iron", "amount": n},
                                  f"{iron} iron bars and {flux} flux stone: make {n} pig iron (the first step "
                                  "to steel)", 5, True))
    else:
        n = max(1, min(pig, spare_iron, flux, fuel if not magma else 99, cfg["steel_batch"]))
        proposals.append(Proposal("steel", {"type": "work_order", "recipe": "steel", "amount": n},
                                  f"{pig} pig iron, {iron} iron bars and {flux} flux stone: make steel "
                                  f"({2 * n} bars)", 5, True))


COAL_STONES = {"COAL_BITUMINOUS": "coke_bituminous", "LIGNITE": "coke_lignite"}


def _coal_rule(s: dict, proposals: list) -> None:
    """Coal the masons may use (0.52 let them have bituminous coal) goes back
    to being kept: it's the smelter's fuel, as coke."""
    for k in sorted(_d(_d(s.get("stone_use")).get("fuel_free"))):
        proposals.append(Proposal("stone", {"type": "allow_stone", "stone": k, "keep": True},
                                  f"{k.lower().replace('_', ' ')} is free for the masons: keep it for coke "
                                  "(the smelter's fuel)", 2))
        return


def _picks_order(s: dict, cfg: dict, proposals: list) -> None:
    """(0.99.4) Picks for more miners while stone is short: DF lets a dwarf
    mine only with a pick, so region2 dug its quarries with 3 miners for 228
    dwarves (57% idle) and every boulder went at once. One pick for every
    picks_per_dwarves dwarves (3 at least, picks_max at most), forged in the
    first of copper, bronze, iron or steel there are bars for (steel last:
    the soldiers want it)."""
    lb = _d(s.get("labor"))
    if (not isinstance(lb.get("picks"), int) or queued(s, {"metal_pick"})
            or any(p.rule == "picks" for p in proposals)):      # (0.105.35) the labour rule's, this cycle
        return
    citizens = int(_d(s.get("dwarves")).get("total") or 0)
    # (0.104.4) and one more for every picks_per_backlog tiles waiting to be dug
    # (Enxah: 93 dwarves, 3 picks, 126 tiles waiting, no stone)
    want = min(cfg["picks_max"], max(3, citizens // cfg["picks_per_dwarves"])
               + int(lb.get("dig") or 0) // cfg["picks_per_backlog"])
    have = int(lb["picks"]) + int(lb.get("soldier_picks") or 0)
    if have >= want or not _has_shop(_d(s.get("buildings")), "MetalsmithsForge"):
        return
    n = want - have
    bars = _d(_d(_d(s.get("military")).get("gear")).get("bars"))
    metal = next((m for m in ("COPPER", "BRONZE", "IRON", "STEEL") if (bars.get(m) or 0) >= n), None)
    if not metal:
        # (0.105.119 item33) fewer bars than picks wanted: half the bars of the
        # first metal that has 2 or more (D, 25 Nov: 20 picks wanted, 16 iron
        # bars, so none ordered while 1217 tiles waited and no pick was left)
        metal = next((m for m in ("COPPER", "BRONZE", "IRON", "STEEL") if (bars.get(m) or 0) >= 2), None)
        if metal:
            n = min(n, int(bars[metal]) // 2)
    if metal:
        proposals.append(Proposal("picks", {"type": "work_order", "recipe": "metal_pick", "amount": n,
                                            "material": f"INORGANIC:{metal}"},
                                  f"stone is short and {have} pick(s) let only {have} dwarves mine: forge {n} "
                                  f"more in {metal.lower()}", 4, True))


PRECIOUS_ORES = {"NATIVE_GOLD", "NATIVE_SILVER", "NATIVE_PLATINUM", "HORN_SILVER", "NATIVE_ALUMINUM"}


def stone_crisis(s: dict, cfg: dict) -> str:
    """(0.104.124) What only stone answers now: ghosts with no slab, the dead
    with no coffin, a fort strained by unhappiness. "" when none."""
    dead = _d(s.get("dead"))
    out = []
    if int(dead.get("ghosts") or 0) > 0:
        out.append(f"{dead.get('ghosts')} ghosts wait for slabs")
    if int(dead.get("unburied") or 0) >= cfg["stone_crisis_unburied"] and int(dead.get("free_tombs") or 0) == 0:
        out.append(f"{dead.get('unburied')} dead wait for coffins")
    import outcomes
    un = outcomes.measure(s).get("unhappy_pct")
    if isinstance(un, (int, float)) and un >= cfg["strain_unhappy_pct"]:
        out.append(f"{un:g}% unhappy")
    return "; ".join(out)


def quarry_size(s: dict, cfg: dict) -> int:
    """(item7) Tiles a quarry asks for: what lifts the masons' stone to twice
    stone_low (at least quarry_min_tiles), never more than the Mining slider's
    quarry size (10-30)."""
    plan_n = mining_plan(_traits(s) if isinstance(s.get("settings"), dict) else {}, cfg)["quarry"]
    usable = int(_d(s.get("stone_use")).get("usable") or 0)
    return max(1, min(plan_n, max(cfg["quarry_min_tiles"], 2 * cfg["stone_low"] - usable)))


def _quarry_stock(su: dict) -> int:
    """Ordinary stone the masons have or are using: free boulders and those a
    job holds (a mason's, a hauler's; 0 from a bridge that doesn't say)."""
    return int(su.get("usable") or 0) + int(su.get("in_job") or 0)


def _quarry_status(su: dict, q: dict) -> dict | None:
    """The bridge's word on the last quarry's tiles, when it is the one the
    memory holds (same spot), else None."""
    st = _d(su.get("quarry"))
    if not st or not isinstance(st.get("pending"), int):
        return None
    if q.get("x") is not None and (st.get("x"), st.get("y"), st.get("z")) != (q.get("x"), q.get("y"), q.get("z")):
        return None
    return st


def note_quarry(s: dict, memory, cfg: dict = PLANNER_CONFIG) -> list:
    """(item7) Bookkeeping, before planning: the last quarry, once dug (the
    bridge's word on its tiles, or quarry_settle_days on), is counted: did
    the stone the masons have (free or in a job) rise? Not twice in a row
    (quarry_norise_strikes): a pause of quarry_backoff_days, doubled each
    time, at most quarry_backoff_max_days. Returns notes."""
    q = getattr(memory, "quarry_seen", None)
    if not isinstance(q, dict) or not isinstance(q.get("tick"), int) or q.get("settled"):
        return []
    su = _d(s.get("stone_use"))
    if not isinstance(su.get("usable"), int):
        return []
    now = abs_tick(s)
    st = _quarry_status(su, q)
    stalled = False
    if st is not None:
        if int(st.get("pending") or 0) > 0:
            # (the marks may stand undug for good: a tile no miner reaches)
            if not now - q["tick"] >= cfg["quarry_stall_days"] * TICKS_PER_DAY:
                return []
            stalled = True
        dug = int(st.get("dug") or 0)
    else:
        if not 0 <= now - q["tick"] < 400 * TICKS_PER_DAY or now - q["tick"] >= cfg["quarry_settle_days"] * TICKS_PER_DAY:
            dug = None
        else:
            return []
    gain = _quarry_stock(su) - int(q.get("before") or 0)
    forbid_up = int(su.get("forbidden") or 0) - int(q.get("forbidden_before") or 0)
    q["settled"], q["gain"] = True, gain
    if stalled and gain <= 0:
        why = f"its tiles stood undug {cfg['quarry_stall_days']} days"
    elif dug == 0:
        why = "its tiles were never dug (the marks were dropped)"
    elif gain <= 0 and forbid_up > 0:
        why = f"its stone lies forbidden ({su.get('forbidden')} boulders of ordinary stone forbidden)"
    elif gain <= 0:
        why = "the stone the masons may use didn't rise (taken as soon as dug, or never reached)"
    else:
        q["strikes"], q["why"] = 0, ""
        return []
    q["strikes"] = int(q.get("strikes") or 0) + 1
    q["why"] = why
    if q["strikes"] >= cfg["quarry_norise_strikes"]:
        pauses = int(q.get("pauses") or 0) + 1
        days = min(cfg["quarry_backoff_max_days"], cfg["quarry_backoff_days"] * 2 ** (pauses - 1))
        q["pauses"], q["until"], q["strikes"] = pauses, now + days * TICKS_PER_DAY, 0
        return [f"quarry: {cfg['quarry_norise_strikes']} quarries in a row brought no stone the masons may use "
                f"({why}): no quarry for {days} days"]
    return []


def quarry_wait(s: dict, memory, cfg: dict = PLANNER_CONFIG) -> str:
    """(item7) Why no quarry now ("" when one may come): the last one still to
    dig, not yet counted, a pause after quarries that brought nothing, or
    ordinary stone lying forbidden (a quarry adds nothing the masons may
    take)."""
    su = _d(s.get("stone_use"))
    now = abs_tick(s)
    forb = int(su.get("forbidden") or 0)
    if forb >= cfg["stone_low"]:
        return (f"{forb} boulders of ordinary stone lie forbidden: no quarry while they do "
                "(unforbid them and the masons have stone)")
    q = getattr(memory, "quarry_seen", None) if memory is not None else None
    if not isinstance(q, dict) or not isinstance(q.get("tick"), int):
        return ""
    if not 0 <= now - q["tick"] < 400 * TICKS_PER_DAY:
        return ""                       # a stale memory (another save, a year gone): forgotten
    until = q.get("until")
    if isinstance(until, int) and 0 <= until - now < 400 * TICKS_PER_DAY:
        days = max(1, -(-(until - now) // TICKS_PER_DAY))
        return f"the last quarries brought no stone the masons may use ({q.get('why') or 'no rise'}): next try in {days} day(s)"
    if q.get("settled"):
        return ""
    st = _quarry_status(su, q)
    if st is not None and int(st.get("pending") or 0) > 0:
        return (f"{st['pending']} of the last quarry's {st.get('tiles') or q.get('tiles')} tiles still to dig "
                f"(x{q.get('x')} y{q.get('y')} z{q.get('z')}): no new quarry till they're dug and counted")
    if st is None and 0 <= now - q["tick"] < cfg["quarry_settle_days"] * TICKS_PER_DAY:
        return f"the last quarry ({q.get('tiles')} tiles) is given {cfg['quarry_settle_days']} days to be dug and counted"
    return ""


def note_quarry_dug(p, r: dict, state: dict, memory, now: int) -> None:
    """(item7) A quarry marked: what it is and the stone the masons had then."""
    if p.action.get("type") != "quarry" or r.get("ok") is not True or p.action.get("dry_run"):
        return
    su = _d(state.get("stone_use"))
    prev = getattr(memory, "quarry_seen", None)
    prev = prev if isinstance(prev, dict) else {}
    memory.quarry_seen = {"tick": now, "tiles": int(r.get("tiles") or 0), "x": r.get("x"), "y": r.get("y"),
                          "z": r.get("z"), "stone": r.get("stone"), "before": _quarry_stock(su),
                          "forbidden_before": int(su.get("forbidden") or 0), "settled": False,
                          "strikes": int(prev.get("strikes") or 0), "pauses": int(prev.get("pauses") or 0)}


def _stone_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """No stone the masons may use: DF keeps "economic" stone (ores, flux
    and the like) from ordinary jobs, and region2's boulders were all
    economic by y52, every stone order standing still. The commonest
    economic stone that is neither ore nor flux is allowed (DF's stone
    settings); without one, stone orders the AI gave that haven't moved are
    cancelled, and the furniture rule makes them in wood."""
    _coal_rule(s, proposals)
    # (0.104.124) an ore freed for the masons in a crisis goes back to being
    # kept once the crisis is over
    freed = list(getattr(memory, "ores_freed", None) or []) if memory is not None else []
    if freed and not stone_crisis(s, cfg):
        k = freed[0]
        proposals.append(Proposal("stone", {"type": "allow_stone", "stone": k, "keep": True},
                                  f"the ghosts are laid and the dead buried: {k.lower().replace('_', ' ')} is kept "
                                  "for the smelter again", 5))
        return
    if not stone_short(s, cfg["stone_low"]):
        # (0.104.117) picks for the digging that waits, stone short or not
        # (Teacheroar: 88 tiles waiting, 9 picks, levels stalled for years)
        if int(_d(s.get("labor")).get("dig") or 0) >= cfg["picks_per_backlog"]:
            _picks_order(s, cfg, proposals)
        return
    su = _d(s.get("stone_use"))
    econ = {k: v for k, v in _d(su.get("economic")).items() if isinstance(v, dict)}
    free = sorted(((int(v.get("n") or 0), k) for k, v in econ.items()
                   if not v.get("ore") and not v.get("flux") and not v.get("fuel")
                   and k not in COAL_STONES and int(v.get("n") or 0) >= cfg["stone_low"]),
                  reverse=True)
    if free:
        n, k = free[0]
        proposals.append(Proposal("stone", {"type": "allow_stone", "stone": k},
                                  f"only {su.get('usable')} boulders of stone the masons may use and {n} of "
                                  f"{k.lower().replace('_', ' ')} kept as \"economic\": let them use it", 3))
        return
    # (0.104.124) no ordinary stone at all and a crisis that stone answers
    # (Teacheroar: 13 ghosts with no slab, 38 dead with no coffin, 73% unhappy,
    # 51 dead in three minutes of tantrums): the commonest ore of a common
    # metal goes to the masons until the crisis is over
    crisis = stone_crisis(s, cfg)
    # (0.105.19) ghosts need a slab each, not 30 boulders: C (3 Nov) had 2
    # ghosts haunting 31 citizens, limonite 27 and tetrahedrite 27, the slab
    # ordered and cancelled as stuck six times in an hour
    ore_min = cfg["stone_ore_min"]
    if int(_d(s.get("dead")).get("ghosts") or 0) > 0:
        ore_min = min(ore_min, cfg["stone_ore_ghost_min"])
    ores = sorted(((int(v.get("n") or 0), k) for k, v in econ.items()
                   if v.get("ore") and k not in PRECIOUS_ORES and int(v.get("n") or 0) >= ore_min),
                  reverse=True)
    if crisis and ores:
        n, k = ores[0]
        proposals.append(Proposal("stone", {"type": "allow_stone", "stone": k, "ore": True},
                                  f"only {su.get('usable')} boulders of stone the masons may use and {crisis}: "
                                  f"let them use {k.lower().replace('_', ' ')} ({n} boulders of ore) until it's over", 2))
        return
    # dig a small quarry in ordinary stone (each tile a boulder), while
    # little other digging waits
    # (0.104.4) with no usable stone at all the quarry comes whatever else waits,
    # every quarry_dry_days at most (Enxah: 126 tiles of bedrooms waited for 3
    # miners, so no quarry for days while no crafts, mugs or jewellery could
    # be made: 42 dwarves badly wanted to craft)
    dig_now = int(_d(s.get("labor")).get("dig") or 0)
    last_q = (memory.last_fired.get("quarry") if memory is not None else None)
    dry = (int(su.get("usable") or 0) == 0
           and (last_q is None or not 0 <= abs_tick(s) - last_q < cfg["quarry_dry_days"] * TICKS_PER_DAY))
    # (item7) one quarry at a time: the last one dug and its boulders counted
    # first, and a pause when quarries bring no stone the masons may use (B,
    # 13 Nov: seven quarries of 4-7 tiles in three minutes, the stone at 8-9)
    wait = quarry_wait(s, memory, cfg)
    # (0.105.88) for the dead (ghosts with no slab, bodies with no tomb):
    # the quarry is survival, not expansion, so a crisis doesn't hold it
    # (E, 23 Nov: 5 ghosts haunting 57, 19 slab orders with no stone,
    # "crisis: ore, quarry wait": the crisis held its own way out);
    # (0.105.89) nor does other digging (E: 295 tiles queued, 2 usable boulders)
    dd = _d(s.get("dead"))
    for_dead = ((int(dd.get("ghosts") or 0) > 0
                 or (int(dd.get("unburied") or 0) >= cfg["stone_crisis_unburied"]
                     and int(dd.get("free_tombs") or 0) == 0))
                and int(su.get("usable") or 0) < cfg["stone_low"])
    if wait:
        notes.append(f"quarry: {wait}")
    elif dig_now < cfg["quarry_when_dig_below"] or dry or for_dead:
        n = quarry_size(s, cfg)
        act = {"type": "quarry", "count": n}
        if for_dead:
            act["for_dead"] = True
        proposals.append(Proposal("quarry", act,
                                  f"only {su.get('usable')} boulders of stone the masons may use"
                                  + (" and the dead wait for slabs or coffins" if for_dead else "")
                                  + ": dig a small quarry in ordinary stone near the fort", 4))
    _picks_order(s, cfg, proposals)
    now = abs_tick(s)
    # (0.105.22) never the dead's slabs and coffins while ghosts walk or bodies
    # wait: they can't be made in wood, and B (3-5 Nov) ordered and cancelled
    # the slab 181 times while 41 ghosts rose (the ore, the quarry and the
    # mason's labour are what get them made)
    dd = _d(s.get("dead"))
    keep = {"stone_slab", "stone_coffin"} if (int(dd.get("ghosts") or 0) > 0
                                             or int(dd.get("unburied") or 0) > 0) else set()
    for k, w in sorted(memory.order_watch.items()) if memory is not None else []:
        if (isinstance(w, dict) and w.get("by_ai") and str(w.get("what", "")).startswith("stone_")
                and str(w.get("what")) not in keep
                and isinstance(w.get("since"), int) and stuck_days(w, now) >= cfg["order_stuck_days"]):   # (r1g8) not the alarm's days
            # (0.105.24) booked as stuck (`stuck`), so the recipe waits its 28-112
            # days and a rule asking again gets the wooden one (stuck_fallback):
            # A (2-5 Nov) cancelled stone_door and stone_slab 276 times, the
            # planned-parts rule ordering stone_door again after each
            proposals.append(Proposal("stone", {"type": "cancel_work_order", "order_id": int(k),
                                                "stuck": str(w.get("what"))},
                                      f"no stone the masons may use and {w.get('what')} hasn't moved in "
                                      f"{(now - watch_since(w)) // TICKS_PER_DAY} days: cancel it (made in wood instead)", 4))
            return
    notes.append(f"only {su.get('usable')} boulders of stone the masons may use (the rest is ore, flux or other "
                 "economic stone): furniture in wood, no stone crafts until more is dug")


def _glass_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.104.95) Glass from the fort's sand (phase 13): green glass crafts
    when the dwarves are idle or there's no rock for crafts. One step a cycle:
    a glass furnace (and a wood furnace when there's no fuel), a sand zone on
    sand the dwarves reach, charcoal for fuel, bags filled with sand at the
    furnace, then the crafts. Only where the geology has sand."""
    sup = _d(s.get("supplies"))
    layers, zones = _l(sup.get("sand_layers")), int(sup.get("sand_zones") or 0)
    if not layers and not zones:
        return
    if young_fort(s, cfg):
        return
    tr = _d(s.get("trade"))
    dw = _d(s.get("dwarves"))
    idle = (dw.get("idle_adults") or 0) / max(1, dw.get("adults") or 1)
    citizens = int(dw.get("citizens") or dw.get("adults") or 0)
    goods_short = (tr.get("goods") or 0) < max(10, citizens * 2)
    if not ((idle >= cfg["idle_share"] or stone_short(s, 10)) and goods_short):
        return
    b = s["buildings"]
    chain = ("collect_sand", "glass_crafts", "make_charcoal")
    if any(queued(s, {r}) for r in chain):
        return
    fuel, bags = int(sup.get("fuel") or 0), int(sup.get("sand_bags") or 0)
    empty_bags = int(sup.get("empty_bags") or 0)
    wood = int(_d(s.get("stocks")).get("wood") or 0)
    if not _has_shop(b, "GlassFurnace"):
        open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
        if not _workshops_busy(open_):
            shops = ["GlassFurnace"] + (["WoodFurnace"] if not _has_shop(b, "WoodFurnace") and fuel < 5 else [])
            proposals.append(Proposal("glass", {"type": "start_project", "kind": "workshops", "shops": shops},
                                      f"the fort has sand ({', '.join(map(str, layers[:2])) or 'a sand zone'}) and "
                                      f"{round(100 * idle)}% of the dwarves idle: build {' and '.join(shops)} for glass", 6))
        return
    if zones == 0:
        proposals.append(Proposal("glass", {"type": "sand_zone"},
                                  "glass is made from sand: a sand collection zone where the dwarves can fill bags", 6))
        return
    if fuel < cfg["glass_fuel_min"]:
        if _has_shop(b, "WoodFurnace") and wood >= 20:
            proposals.append(Proposal("glass", {"type": "work_order", "recipe": "make_charcoal", "amount": 3},
                                      f"the glass furnace burns fuel and the fort has {fuel}: make charcoal "
                                      f"({wood} logs)", 6, True))
        else:
            notes.append(f"glass waits for fuel ({fuel} coal; charcoal needs a wood furnace and 20 logs)")
        return
    if bags < cfg["glass_sand_bags"]:
        if empty_bags:
            n = min(cfg["glass_sand_bags"] - bags, empty_bags)
            proposals.append(Proposal("glass", {"type": "work_order", "recipe": "collect_sand", "amount": n},
                                      f"glass is made from bags of sand ({bags} filled): fill {n} at the glass furnace",
                                      6, True))
        else:
            notes.append("glass waits for an empty bag to fill with sand")
        return
    n = min(bags, fuel, 5)
    proposals.append(Proposal("glass", {"type": "work_order", "recipe": "glass_crafts", "amount": n},
                              f"{round(100 * idle)}% of the dwarves are idle and there are only {tr.get('goods') or 0} "
                              f"crafts to sell: make {n} of green glass", 6, True))


def _smelting_rule(s: dict, memory, cfg: dict, rules_: dict, proposals: list, notes: list) -> None:
    """When weapon-grade metal runs low, import DFHack's own smelting orders
    once: they smelt ore whenever bars drop below their limits."""
    gear = _d(_d(s.get("military")).get("gear"))
    bars = _d(gear.get("bars"))
    if not bars and "bars" not in gear:
        return                                       # older bridge: unknown
    total = sum(v for v in bars.values() if isinstance(v, (int, float)))
    if total >= cfg["smelt_when_bars_below"] or "smelting" in memory.libraries_imported:
        return
    if not rules_["import_smelting"]:
        return
    if "ore_stock_by" in _d(s.get("industry")):
        return              # bridge 0.49+: the AI gives its own smelting orders (_industry_rules)
    furnaces = _d(_d(s.get("buildings")).get("furnaces"))
    if not (furnaces.get("Smelter") or furnaces.get("MagmaSmelter")):
        if not _d(_d(s.get("industry")).get("ores")):
            notes.append(f"only {total} bars of weapon-grade metal, and no ore uncovered near the fort yet "
                         "(the AI builds a smelter once there is)")
        return                         # (the industry rule builds the furnaces once ore is known)
    proposals.append(Proposal("smelting", {"type": "import_orders", "library": "smelting"},
                              f"only {total} bars of weapon-grade metal: add DFHack's smelting orders "
                              "(they smelt ore whenever bars run low)", 5))
