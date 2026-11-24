"""planner_industry_disposal: the slow game, the clutter and the disposal of
what the fort throws away (split out of planner_industry in r7 d4, moved
unchanged). planner_industry re-exports every name here."""

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

__all__ = ["_slow_game_rules", "_clutter_rules", "DISPOSAL_RULES", "DISPOSAL_REASON_WORDS", "disposal_report", "disposal_places_dump", "_standing_key", "_unknown_reachable", "_disposal_rules"]


def _slow_game_rules(s: dict, citizens: int, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """The game runs slowly (FPS measured by the overseer): besides holding
    newcomers and new luxury levels, what the counts point at. Many items:
    a garbage dump outside, then worn-out clothes lying about marked for it
    (DFHack's cleanowned, at most once a week). Big herds: autobutcher (the
    tools rule). Said with the counts either way."""
    c = _d(_d(s.get("logistics")).get("counts"))
    items, units = int(c.get("items") or 0), int(c.get("units") or 0)
    if not c:
        return
    # (0.104.113) what fills the map, counted once a week while slow
    cen = _d(getattr(memory, "census", None)) if memory is not None else {}
    if not isinstance(cen.get("tick"), int) or not 0 <= abs_tick(s) - cen["tick"] < 7 * TICKS_PER_DAY:
        proposals.append(Proposal("census", {"type": "census"},
                                  f"{units} creatures and {items} items on the map: count what they are", 6))
    notes.append(f"the game runs slowly (FPS {s.get('fps_low')}): {items} items, {units} creatures, "
                 f"{c.get('jobs')} jobs on the map")
    if items >= cfg["fps_items_heavy"]:
        zones = _d(_d(s.get("buildings")).get("zones"))
        # (0.105.27 fixes) _disposal_rules places the dump only at Rules `dump` or
        # `destroy`; at `store` or `melt` this old rule still makes one when slow
        if (not zones.get("Dump") and not _d(_d(s.get("buildings")).get("clearing")).get("dump")
                and not disposal_places_dump(s)):
            proposals.append(Proposal("dump", {"type": "place_surface", "kind": "dump"},
                                      f"{items} items on the map slow the game: make a garbage dump outside "
                                      "for worn-out things", 5))
        # (0.104.149) no more `tidy` (DFHack cleanowned scattered x) here: it
        # took every owned thing off the floor (the trinkets just given) and
        # every slightly worn garment off its wearer, all carried to the dump
        # (68 times a night in Teacheroar), and the dump keeps them on the map;
        # prune_remains' "clothes" below rots the thrown-down clothes for real
    # (0.105.3) B (2 Nov): 17,471 items at 1-3 FPS, so none of the clean-ups
    # below (all behind fps_items_heavy, 30,000) ran. The census' own counts
    # decide them now (_clutter_rules, run at any speed); `heavy` still lets
    # the old corpses rot when the census hasn't counted yet
    _clutter_rules(s, cfg, proposals, notes, memory, heavy=items >= cfg["fps_items_heavy"])


def _clutter_rules(s: dict, cfg: dict, proposals: list, notes: list, memory=None, heavy: bool = False) -> None:
    """(0.105.3) What the last census says lies about, cleared: loose spider
    webs far from the fort (remove_webs), dead creatures on the game's unit
    list (fix/dead-units) and old corpses on the ground (deteriorate). Lower
    bars while the game runs slowly. Called by the slow-game rules and, at any
    speed, by the planner itself (with heavy False)."""
    slow = bool(s.get("fps_low"))
    now = abs_tick(s)
    cen = _d(getattr(memory, "census", None)) if memory is not None else {}
    # a census older than four weeks says too little to act on (heavy alone still prunes)
    if not (isinstance(cen.get("tick"), int) and 0 <= now - cen["tick"] < 28 * TICKS_PER_DAY):
        cen = {}
    last = (lambda r: memory.last_fired.get(r)) if memory is not None else (lambda r: None)

    def due(rule, days):
        t = last(rule)
        return t is None or not 0 <= now - t < days * TICKS_PER_DAY

    ic = _d(_d(cen.get("items")).get("counts"))
    items = int(_d(_d(s.get("logistics")).get("counts")).get("items") or ic.get("total") or 0)
    # (0.105.3) loose webs outside the fort's areas (the census' webs_removable,
    # from 0.105.3's bridge): past 1,000 while slow, past 5,000 at any speed, a
    # week apart, a batch a day while the last call left more. Webs are silk
    # for cloth, but thousands far off cost more FPS than their thread is worth
    far = ic.get("webs_removable")
    # (0.105.47, J1) not while a strange mood or the silk reserve wants silk (the
    # webs are its only source here: I7a, 20 moods died on silk while remove_webs
    # took 20,000-36,000 webs a fort); the far ones go once plenty lie in reach
    from planner_mood_help import webs_hold
    hold = webs_hold(s, cfg) if (isinstance(far, int) or heavy) else ""
    if hold and (isinstance(far, int) and far >= (cfg["remove_webs_slow_min"] if slow else cfg["remove_webs_min"])):
        notes.append(hold)
        far = None
    if isinstance(far, int):
        more = bool(_d(cen.get("webs_left")).get("more"))
        if (far >= (cfg["remove_webs_slow_min"] if slow else cfg["remove_webs_min"])
                and due("remove_webs", cfg["remove_webs_more_days"] if more else cfg["remove_webs_days"])):
            kept = _d(_d(_d(cen.get("items")).get("webs")).get("kept"))
            near = int(kept.get("fort") or 0)
            proposals.append(Proposal("remove_webs", {"type": "remove_webs", "max": cfg["remove_webs_max"]},
                                      f"{far} spider webs lie far from the fort ({ic.get('webs')} in all, "
                                      f"{items} items on the map): remove up to {cfg['remove_webs_max']}"
                                      + (f"; the {near} near the fort stay for the weavers" if near else ""), 7))
    elif heavy and slow and not hold:
        # (0.104.116) a census from an older bridge: every web, a season apart
        webs = ic.get("webs")
        if isinstance(webs, int) and webs >= cfg["webs_clear_min"] and due("webs", 84):
            proposals.append(Proposal("webs", {"type": "clear_webs"},
                                      f"{webs} spider webs lie in the caverns, a big share of the {items} items "
                                      "slowing the game: clear them (DFHack's clear-webs)", 7))
    # (0.104.158) dead creatures on the game's unit list: DFHack's
    # fix/dead-units scrubs the slaughtered, nameless and foreign dead a month
    # old, never the fort's own race (its isOwnRace test; merchants' and
    # diplomats' too are kept). (0.105.3) B: 151 scrubbable (100 turkeys),
    # under the old 1,000: now 100 while slow, two weeks apart
    uc = _d(_d(cen.get("units")).get("counts"))
    scrub = uc.get("dead_scrubbable")
    if isinstance(scrub, int):
        lo, days = ((cfg["dead_scrub_slow_min"], cfg["dead_scrub_slow_days"]) if slow
                    else (cfg["dead_scrub_min"], cfg["dead_scrub_days"]))
        if scrub >= lo and due("dead_units", days):
            proposals.append(Proposal("dead_units", {"type": "scrub_dead_units"},
                                      f"{uc.get('dead')} of the {uc.get('total')} creatures on the game's list are dead "
                                      f"(up to {scrub} slaughtered or nameless): clear the old ones (DFHack's "
                                      "fix/dead-units; the fort's own dead are kept)", 7))
    # (0.105.33 fix) a strange mood wants bone or shell, or the fort is at or
    # under its bone reserve (planner_moods MOOD_RESERVES), after a prune put
    # usable parts on deteriorate's timer (it stays on in the save): taken off
    # it, so the loose bones and shells stop rotting
    mood_bone = any(isinstance(x, dict) and mood_kind(x) in ("bone", "shell")
                    for m in _l(_d(s.get("moods")).get("list")) if isinstance(m, dict)
                    for x in _l(m.get("missing")))
    bones = _d(s.get("needs")).get("bones")
    low = (isinstance(bones, (int, float)) and not isinstance(bones, bool)
           and bones <= cfg.get("reserve_bones", 5))
    if (mood_bone or low) and last("prune") is not None and due("prune_keep_parts", 7):
        proposals.append(Proposal("prune_keep_parts", {"type": "prune_remains", "keep": ["usable-parts"]},
                                  ("a strange mood wants bone or shell" if mood_bone else
                                   f"the fort has {bones} bone(s), at or under its reserve")
                                  + ": loose bones and shells come off deteriorate's timer (an earlier prune "
                                    "put them on it)", 5))
    if not slow:
        return
    # (0.104.0) old remains rot away: non-entombed corpses and body parts
    # nobody can craft with (DFHack deteriorate; stays on in the save)
    # (0.104.115) the census says what lies about: thousands of butchered
    # bones and shells, or worn clothes thrown down, rot away too
    ground = {str(_d(x).get("name")): int(_d(x).get("n") or 0)
              for x in _l(_d(cen.get("items")).get("on_ground"))}
    # (0.105.3) B: 69 corpses, 76 parts and 52 remains on the ground with
    # 17,471 items: rotted from 100 while slow, but only with no citizen
    # unburied (deteriorate spares only the entombed, so a dwarf's body
    # waiting for a coffin would rot too)
    bodies = sum(ground.get(k, 0) for k in ("CORPSE", "CORPSEPIECE", "REMAINS"))
    unburied = _d(s.get("dead")).get("unburied")
    few_bodies = bodies >= cfg["corpses_ground_min"] and unburied == 0
    if not (heavy or few_bodies):
        return
    extra = []
    if ground.get("CORPSEPIECE", 0) >= cfg["prune_parts_min"]:
        # (0.105.33) not while a strange mood asks for bone or shell (on hand
        # or not: what lies loose would rot), nor with the fort at or under
        # its bone reserve (planner_moods MOOD_RESERVES): a failed mood kills
        # (mood_bone and low: read above)
        if not (mood_bone or low):
            extra.append("usable-parts")
    worn = {str(_d(x).get("name")): int(_d(x).get("n") or 0) for x in _l(_d(cen.get("items")).get("worn"))}
    if sum(worn.get(k, 0) for k in ("SHOES", "GLOVES", "PANTS", "ARMOR", "HELM")) >= cfg["prune_worn_min"]:
        extra.append("clothes")
    action = {"type": "prune_remains"}
    if extra:
        action["extra"] = extra
    what = (" (and " + ", ".join({"usable-parts": f"{ground.get('CORPSEPIECE', 0)} bones, shells and hair on the "
                                                   "ground", "clothes": "worn clothes thrown down"}[e]
                                  for e in extra) + ")") if extra else ""
    if heavy:
        reason = (f"{items} items on the map slow the game: old corpses and useless body "
                  f"parts lying about rot away{what} (entombed dead are kept)")
    else:
        reason = (f"{bodies} corpses and remains lie on the ground while the game runs slowly: they rot "
                  f"away{what} (no citizen waits for burial; entombed dead are kept)")
    proposals.append(Proposal("prune", action, reason, 7))


# (0.105.27) The rules that dispose of forbidden items, one rule each (each
# with its own `<rule>_cooldown_ticks` in planner_config)
DISPOSAL_RULES = ("disposal_unforbid", "disposal_melt", "disposal_dump", "disposal_place_dump",
                  "disposal_empty", "disposal_orders")
# the game's own reasons for a forbidden item that are worth storing again
DISPOSAL_REASON_WORDS = {"used_ammo": "used bolts and arrows", "other_dead": "the enemy's and animals' dead and gear",
                         "own_dead": "the buried dead's belongings", "unknown": "items forbidden for no game reason"}


def disposal_report(s: dict) -> dict | None:
    """(0.105.27) The bridge's disposal section (lua/ai-disposal.lua), or None
    from an older bridge or when it failed: then no disposal action exists."""
    d = s.get("disposal")
    return d if isinstance(d, dict) and "error" not in d else None


def disposal_places_dump(s: dict, rules: dict | None = None) -> bool:
    """(0.105.27 fixes) Whether _disposal_rules sees to the garbage dump: a
    disposal report and the Rules key at `dump` or `destroy`. Otherwise (no
    report, or `store` / `melt`) the slow-game rule still makes one."""
    if disposal_report(s) is None:
        return False
    rules = rules or player_rules(s)
    return rules.get("disposal", "destroy") in ("dump", "destroy")


def _standing_key(standing: dict, name: str) -> str | None:
    """The key a standing order goes under in dead.standing ("gather_refuse"
    or the global's full name), or None when the game hasn't it."""
    for k in (name, "standing_orders_" + name):
        if k in standing:
            return k
    return None


def _unknown_reachable(fb: dict, reason: dict) -> tuple[int, str]:
    """(0.105.28) The forbidden items of no game reason the fort can reach
    outside the caverns (census forbidden.unknown_reachable), and where they
    lie in words ("on the surface (12) and inside the fort (3)").
    (0.105.30 live fixes) A census from before the field (0.105.27's): 0, so
    no Needs you from it. Its by_reason.unknown held the caverns' REMAINS
    (8 Nov: E's 410 and F's 366 "for no reason the game gives" were all
    REMAINS), and the first cycles on 0.105.28 still read that census ("about
    the map") until the next count; the census since has the field (E, F:
    0-9, the dead's own gear and a bard's instruments)."""
    n = fb.get("unknown_reachable")
    if not isinstance(n, (int, float)) or isinstance(n, bool):
        return 0, "about the map"
    uw = _d(fb.get("unknown_where"))
    parts = [f"{label} ({int(uw[k])})" for k, label in (("surface", "on the surface"), ("inside", "inside the fort"))
             if isinstance(uw.get(k), (int, float)) and uw[k] > 0]
    return int(n), " and ".join(parts) if parts else "within the fort's reach (not in the caverns)"


def _disposal_rules(s: dict, cfg: dict, proposals: list, notes: list, memory=None, rules: dict | None = None) -> None:
    """(0.105.27) Forbidden items (lock symbols) lie about everywhere: the
    game's standing orders forbid used ammo and the dead's things, and what it
    dumps lands forbidden. The DF way first, then DFHack, as far as the Rules
    key `disposal` goes (store < melt < dump < destroy, each doing the ones
    before): unforbid what is worth storing (the haulers take it), mark surplus
    metal to melt, mark junk for a garbage dump (one placed when there is none,
    inside for a fort that keeps to itself), and past disposal_destroy_min
    items in the dump DFHack removes them. Nothing during a siege. The counts
    come from the census (items.forbidden), taken again a few days after a
    batch; the dump's from the disposal report. The bridge keeps its own
    guards (danger, siege, sealed caverns, the cistern, artifacts, owned
    things, the player's items)."""
    dis = disposal_report(s)
    if dis is None:
        return
    rules = rules or player_rules(s)
    level = DISPOSAL_LEVELS.index(rules["disposal"]) if rules.get("disposal") in DISPOSAL_LEVELS else 3
    player_items = bool(rules.get("disposal_player_items"))
    keep_enemy = bool(rules.get("keep_enemy_gear"))
    now = abs_tick(s)
    last = (lambda r: memory.last_fired.get(r)) if memory is not None else (lambda r: None)
    cen = _d(getattr(memory, "census", None)) if memory is not None else {}
    fresh = isinstance(cen.get("tick"), int) and 0 <= now - cen["tick"] < cfg["disposal_census_days"] * TICKS_PER_DAY
    fb = _d(_d(cen.get("items")).get("forbidden")) if fresh else {}
    if fb and not isinstance(fb.get("corpses"), dict):
        # (0.105.27 fixes) a census from before the bodies were counted apart:
        # its other_dead holds bodies no action touches, so count again first
        fresh, fb = False, {}
    # (0.105.27 fixes) by_reason holds no bodies (the census counts them apart,
    # forbidden.corpses): no action here touches a body, so none asks for one
    reason = {k: int(v or 0) for k, v in _d(fb.get("by_reason")).items() if isinstance(v, (int, float))}

    def counted_since(rule):
        """A census taken after this rule's last batch: its counts show what is left."""
        t = last(rule)
        return fresh and (t is None or cen["tick"] > t)

    # count again: never counted (or a month ago), or a batch done since the last count
    done_since = [r for r in DISPOSAL_RULES if r != "disposal_orders" and isinstance(last(r), int)
                  and fresh and last(r) >= cen["tick"]]
    if ((not fresh or (done_since and now - cen["tick"] >= cfg["disposal_recount_days"] * TICKS_PER_DAY))
            and not any(p.rule == "census" for p in proposals)):
        proposals.append(Proposal("census", {"type": "census"},
                                  "count the forbidden items lying about again" if fresh else
                                  "count what lies about the map, forbidden items too", 7))

    # the player's own forbidden things (no game reason): theirs unless the switch says otherwise.
    # (0.105.28) Only those the fort can reach outside the caverns (unknown_reachable):
    # the caverns' and the unreachable ones are the game's, not the player's. A census
    # without the field falls back on by_reason.unknown.
    unknown, where = _unknown_reachable(fb, reason)
    if unknown > cfg["disposal_unknown_note"] and not player_items:
        # (0.105.35) nothing waits for the player: a note. The Rules switch
        # (disposal_player_items, "Yours too") is about the player's own things
        # and stays theirs; off, the AI leaves these alone and goes on
        notes.append(f"{unknown} items lie forbidden {where} for no reason the game gives (not the dead's, "
                     "not used ammo, not dumped): they may be yours, so the AI leaves them where they lie and "
                     "disposes of the rest (the Rules' \"Yours too\", disposal_player_items, is off)")

    # a siege: the haulers stay in (the bridge refuses too); said once a cycle
    threats = _l(_d(s.get("others_on_map")).get("threats"))
    siege = bool(dis.get("siege")) or any(isinstance(t, dict) and t.get("invader") for t in threats)
    if siege:
        if fb.get("total"):
            notes.append(f"a siege is on: the {fb.get('total')} forbidden items wait until it is over")
        return

    st_ = _d(_d(s.get("dead")).get("standing"))
    unburied = _d(s.get("dead")).get("unburied")
    # 1. the game's refuse order: the haulers take corpses and remains to the refuse pile.
    # The dead-items orders stay as they are (the rules below unforbid instead)
    key = _standing_key(st_, "gather_refuse")
    if key is not None and not st_.get(key):
        if last("disposal_orders") is None:
            proposals.append(Proposal("disposal_orders", {"type": "set_standing_orders", "orders": {key: 1}},
                                      "the game's standing order to gather refuse is off, so corpses and remains "
                                      "lie where they fell: switch it on", 6))
        elif not 0 <= now - last("disposal_orders") < cfg["disposal_orders_cooldown_ticks"]:
            notes.append("the game's standing order to gather refuse is off again after the AI switched it on: "
                         "left as you set it")

    # 1b. (0.105.99) the game's order to gather refuse from outside: DF's
    # haulers dump nothing that lies under the sky while it is off (the wiki's
    # Dump and Refuse pages: it "also controls the collection of dumped items
    # outside your fortress"). B (24 Nov): 135 items marked for the dump (89
    # of them outside, the dead birds by the gate, a visitor's body), the
    # order off, 77 refuse haulers and not one DumpItem job; dumped_items 0.
    # Switched on while marked items lie outside and a dump zone stands; set
    # back off by the player after the AI set it, it is left as they set it.
    okey = _standing_key(st_, "gather_refuse_outside")
    out_marked = dis.get("marked_dump_outside")
    out_n = out_marked if isinstance(out_marked, int) and not isinstance(out_marked, bool) else None
    # (0.105.99, merge) only while nothing that can reach the dwarves is about
    # (B, 24 Nov: agitated giant birds and a hoary marmot killed four outside
    # that hour), and set back off by the AI itself once the outside is clear
    # of marked items or a danger comes: the haulers don't stay out for good
    reach = bool(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"))
    t_on, t_off = last("disposal_outside"), last("disposal_outside_off")
    ai_on = t_on is not None and (t_off is None or t_off < t_on)
    if okey is not None and st_.get(okey) and ai_on and (reach or out_n == 0):
        proposals.append(Proposal("disposal_outside_off", {"type": "set_standing_orders", "orders": {okey: 0}},
                                  ("a danger can reach the dwarves" if reach else
                                   "no item marked for the dump lies outside any more")
                                  + ": the game's standing order to gather refuse from outside, which the AI "
                                    "switched on, goes back off (the haulers stay in)", 3))
    elif (okey is not None and not st_.get(okey) and out_n and out_n > 0 and not reach
            and any(isinstance(z, dict) for z in _l(dis.get("dump_zones")))):
        # (merge) after the AI's own switch-off, two days clear before on again: a danger
        # seen and gone each cycle doesn't flip the order every cycle
        if t_on is None or (t_off is not None and t_off >= t_on and not 0 <= now - t_off < 2 * 1200):
            proposals.append(Proposal("disposal_outside", {"type": "set_standing_orders", "orders": {okey: 1}},
                                      f"{out_n} items marked for the garbage dump lie outside and the game's "
                                      "standing order to gather refuse from outside is off, so no hauler takes "
                                      "them: switch it on while nothing dangerous is about", 6))
        elif not 0 <= now - t_on < cfg["disposal_outside_cooldown_ticks"]:
            notes.append(f"{out_n} items marked for the dump lie outside and the game's standing order to "
                         "gather refuse from outside is off again after the AI switched it on: left as you set "
                         "it, so they stay where they lie")
    elif out_n and out_n > 0 and reach and okey is not None and not st_.get(okey):
        notes.append(f"{out_n} items marked for the dump lie outside: the haulers wait for the danger to go")

    # 2. store: unforbid what is worth keeping (the haulers store it)
    why = ["used_ammo"]
    if not unburied:
        why.append("own_dead")          # bodies waiting for a tomb are the burial rule's (unforbid_dead)
    why.append("other_dead")
    if player_items:
        why.append("unknown")
    n_un = sum(reason.get(r, 0) for r in why)
    if n_un >= cfg["disposal_unforbid_min"] and counted_since("disposal_unforbid"):
        most = min(cfg["disposal_unforbid_max"], DISPOSAL_ACTION_MAX)
        parts = ", ".join(f"{reason[r]} {DISPOSAL_REASON_WORDS[r]}" for r in why if reason.get(r))
        a = {"type": "unforbid_items", "reasons": why, "max": most}
        if player_items:
            a["player_items"] = True
        proposals.append(Proposal("disposal_unforbid", a,
                                  f"{n_un} items worth keeping lie forbidden ({parts}): unforbid up to {most} so the "
                                  "haulers store them (none near danger, owned or made by the AI)", 8))

    # 3. melt: surplus and worn metal to the smelters (never masterworks or artifacts)
    metal = int(fb.get("metal") or 0)
    smelters = int(dis.get("smelters") or 0) + int(dis.get("magma_smelters") or 0)
    marked = int(dis.get("marked_melt") or 0)
    # (0.105.30 live fixes) the census' `meltable` (ai-disposal melt_check, the
    # bridge's own test: loose, worn or the enemy's, no tool, masterwork or
    # squad's gear) when it has one: the raw forbidden-metal count asked
    # mark_melt 49 times on 8 Nov for gear the bridge then refused ("no worn
    # or enemy metal gear may be marked"). Nothing meltable: nothing asked.
    melt_key = "meltable_keep_enemy" if keep_enemy else "meltable"
    meltable = fb.get(melt_key) if isinstance(fb.get(melt_key), int) and not isinstance(fb.get(melt_key), bool) else None
    if meltable is not None:
        metal = meltable
    if (level >= 1 and metal >= (cfg["disposal_melt_min"] if meltable is None else 1)
            and counted_since("disposal_melt")):
        if not smelters:
            notes.append(f"{metal} forbidden metal items could be melted down, but the fort has no smelter")
        elif marked >= cfg["disposal_melt_backlog"]:
            notes.append(f"{marked} items marked to melt still wait for the smelters: no more marked yet")
        else:
            most = min(cfg["disposal_melt_max"], DISPOSAL_ACTION_MAX)
            proposals.append(Proposal("disposal_melt", {"type": "mark_melt", "max": most, "keep_masterwork": True,
                                                         "keep_enemy_gear": keep_enemy},
                                      (f"{metal} worn or enemy metal items lie loose" if meltable is not None
                                       else f"{metal} metal items lie forbidden")
                                      + f": mark up to {most} surplus or worn ones to "
                                      "melt into bars (never masterworks or artifacts"
                                      + ("; the enemy's gear is kept, as the Rules say)" if keep_enemy else ")"), 7))

    # (0.105.48, A2-4) the items marked to melt (the AI's or the player's)
    # want a smelter order: placed here, not by the mark_melt action, so the
    # order check (fuel, a free smelter) and the stuck hold see it
    if level >= 1 and marked > 0 and smelters and dis.get("melt_order") is None and not any(
            isinstance(o, dict) and (o.get("recipe") == "melt_metal" or o.get("job") == "MeltMetalObject")
            and int(o.get("amount_left") or 0) > 0 for o in _l(s.get("orders"))):
        n = min(marked, 20)
        proposals.append(Proposal("disposal_melt_order", {"type": "work_order", "recipe": "melt_metal", "amount": n},
                                  f"{marked} items are marked to melt and no smelter order melts them: order "
                                  f"{n} melted down", 7))

    if level < 2:
        return
    # 4. dump: worn clothes, rags, rotten things and the enemy's non-metal junk to a garbage dump
    zones = [z for z in _l(dis.get("dump_zones")) if isinstance(z, dict)]
    worn = int(fb.get("worn") or 0)
    # (0.105.27 fixes) "free" always: worn clothes and rotten things nobody
    # forbade are junk whatever the forbidden reasons, and the list is never
    # empty (the bridge refuses an empty one: War-hold with dead unburied)
    dump_why = ["free"] + (["other_dead"] if not keep_enemy else [])
    if not unburied:
        dump_why.append("own_dead")
    if player_items:
        dump_why.append("unknown")
    junk = worn + sum(reason.get(r, 0) for r in dump_why if r != "own_dead")
    traits = _traits(s) if isinstance(s.get("settings"), dict) else {}
    inside = (int(traits.get("outsiders", 0) or 0) <= -50 or int(traits.get("surface", 0) or 0) <= -50)
    if not zones and (junk >= cfg["disposal_dump_min"] or int(dis.get("marked_dump") or 0) > 0):
        proposals.append(Proposal("disposal_place_dump", {"type": "place_dump", "inside": inside},
                                  f"{junk} worn or useless items lie about and there is no garbage dump: make one "
                                  + ("inside the fort, near the entrance (a fort that keeps to itself)" if inside
                                     else "outside"), 6))
    elif zones and junk >= cfg["disposal_dump_min"] and counted_since("disposal_dump"):
        rot = any(p.rule == "prune" and "clothes" in _l(p.action.get("extra")) for p in proposals)
        if int(dis.get("marked_dump") or 0) >= cfg["disposal_dump_backlog"]:
            notes.append(f"{dis.get('marked_dump')} items marked for the dump still wait for the haulers")
        elif rot:
            notes.append("worn clothes rot away this cycle (the game runs slowly): nothing marked for the dump")
        else:
            most = min(cfg["disposal_dump_max"], DISPOSAL_ACTION_MAX)
            proposals.append(Proposal("disposal_dump", {"type": "mark_dump", "reasons": dump_why, "max": most},
                                      f"{worn} worn clothes and other junk lie about"
                                      + (f" ({reason.get('other_dead')} with the enemy's and animals' dead)"
                                         if "other_dead" in dump_why and reason.get("other_dead") else "")
                                      + f": mark up to {most} (rags, rotten and worn non-metal things) for the "
                                      "garbage dump", 7))

    # 5. destroy: what piles up in the dump past the limit, removed by DFHack (never artifacts)
    dumped = int(dis.get("dumped_items") or 0)
    if level >= 3 and zones and dumped >= cfg["disposal_destroy_min"]:
        most = min(cfg["disposal_empty_max"], DISPOSAL_ACTION_MAX, dumped)
        proposals.append(Proposal("disposal_empty", {"type": "empty_dump", "max": most},
                                  f"{dumped} items lie in the garbage dump (past {cfg['disposal_destroy_min']}): "
                                  f"remove up to {most} of them for good (DFHack's autodump destroy; never "
                                  "artifacts), so they no longer slow the game", 8))
