"""planner_building: part of the planner (split out of planner.py in 0.104.83; see planner.py)."""

from __future__ import annotations
import math
import re
from culture import layout_style, new_history, pick_stone, profile_from, stone_for
import design  # (D0) the design language's naming
from learning import held_levels
import customs
import masterplan
import phases
from quirks import has_rule
from digest import _d, _l, normalize
from planner_core import *  # noqa: F401,F403
from planner_construct import _soil_floor_rule  # (0.105.30) block floors over a finished hall's soil
from planner_growth import *  # noqa: F401,F403  (13c: split out by theme)
from planner_wells import *  # noqa: F401,F403  (13c: split out by theme)
from planner_garden import garden_pace  # (0.105.47) the statue gardens sooner by Agriculture
from planner_alloys import gear_metals  # (fix41) tin and bismuth kept for bronze while there is no iron
from planner_building_stores import *  # noqa: F401,F403  (r7 d4: split out by theme)
from planner_building_rooms import *  # noqa: F401,F403  (r7 d4: split out by theme)

__all__ = ["STUCK_FALLBACKS", "stuck_fallback", "magma_access", "GROWTH", "GROWTH_EXTRA_SCORE", "GROWTH_MAX", "growth_want", "growth_candidates", "settled_times", "growth_wait", "GROWTH_SOLDIERS", "GROWTH_ZONES", "GROWTH_MAX_OF", "GROWTH_AT", "TRAIT_NAMES_SHORT", "FURNITURE_RECIPES", "SHOP_PIECE_RECIPES", "waiting_shops", "METAL_FURNITURE", "spare_metal", "WOODEN_FURNITURE", "BASIC_WORKSHOPS", "BASIC_STOCKPILES", "memorial_due", "_well_rule", "_well_lid_rule", "cavern_danger", "_planned_note", "_planned_parts_rule", "planned_wants", "_water_zone_rule", "cavern_well_need", "cavern_points", "cavern_action", "cavern_well_safe", "WELL_PARTS_SHOPS", "chain_metal", "well_parts_plan", "_well_parts", "_room_repair_rule", "_water_traffic_rule", "_cleanup_rule", "STORE_GROW", "stone_tidiness", "jail_plan", "cistern_pop", "tavern_factor", "full_stores", "LEARNING_NEEDS", "_stairwell_rule", "WATER_WORDS", "water_summary", "_water_rules", "CISTERN_WORDS", "_cistern_parts", "_cistern_rule", "_deep_notes", "good_times", "ORDINALS", "garden_name", "_pop_cap_rule", "fort_strain", "hospital_shortfall", "dining_shortfall", "social_shortfall", "SOCIAL_KINDS", "_join_rule", "_dig_stall_rule", "_shrink_rule", "room_size", "_project_rules", "CHARACTER_KINDS", "is_character_level", "character_slot_reserved", "character_slot_filter", "temple_size", "more_temple", "has_grand_temple", "piety_slot", "LADDER_BASE", "LADDER_TRAITS", "_ladder_kind", "_ladder_word", "ladder_score", "tombs_short", "PLACEMENT_CUSTOMS", "apply_customs", "customs_pass"]


def social_shortfall(s: dict, cfg: dict) -> list:
    """(0.104.137) [(kind, why)] for taverns and temples too few for the dwarves
    who badly miss what they give: one for every `*_badly_per` of them (the
    worst of the needs counted), up to `social_halls_max`, once one stands."""
    nd = _d(_d(s.get("needs")).get("needs"))
    locs = _d(_d(s.get("locations")).get("count"))
    listing = [e for e in _l(_d(s.get("locations")).get("list")) if isinstance(e, dict)]
    cit = int(_d(s.get("dwarves")).get("total") or 0)
    # (0.105.51, R3 fort B) arguments: B's 83 dwarves had one tavern of its
    # own and the stop-gap laid over its 6-table dining hall, where they ate,
    # drank and talked; arguments (31-68 citizens a month) came with the crowd
    argue = 0
    for c in _l(_d(_d(s.get("needs")).get("stress_causes")).get("causes")):
        if isinstance(c, dict) and c.get("thought") == "Argument":
            argue = int(c.get("citizens") or 0)
    out = []
    for kind, (where, needs, per_key) in SOCIAL_KINDS.items():
        have = int(locs.get(where) or 0)
        if have < 1:
            continue                                  # the first is the ladder's (and the urgent rules')
        # (0.105.51) a stop-gap laid over a dining hall is no hall of its own
        stopgap = sum(1 for e in listing if e.get("type") == where and e.get("over_dining"))
        if not (stopgap and have - stopgap >= 1):
            stopgap = 0
        have -= stopgap
        badly = max([int(_d(nd.get(n)).get("badly") or 0) for n in needs] or [0])
        # (0.104.146) or every distracted dwarf, at a wider spacing: Teacheroar's
        # 93 distracted for want of prayer (40 badly) held at 2 temples, one of
        # them for all gods; 128 wanting friends (68 badly) at 3 taverns
        dist = max([int(_d(nd.get(n)).get("distracted") or 0) for n in needs] or [0])
        want = min(cfg["social_halls_max"],
                   max(1 + badly // cfg[per_key], 1 + dist // cfg["social_distracted_per"]))
        crowd = (kind == "tavern" and cit > 0 and argue >= cfg["argument_crowd_share"] * cit
                 and have < min(cfg["social_halls_max"], 1 + cit // cfg["tavern_crowd_per"]))
        if ((badly >= cfg["social_badly_share"] * cit or dist >= cfg["social_distracted_share"] * cit)
                and have < want) or crowd:
            words = ", ".join(f"{n} {int(_d(nd.get(n)).get('distracted') or 0)} distracted "
                              f"({int(_d(nd.get(n)).get('badly') or 0)} badly)" for n in needs)
            out.append((kind, f"{have} {kind}(s) for {cit} dwarves"
                              + (" (not counting the stop-gap in the dining hall)" if stopgap else "")
                              + (f", {argue} citizens upset by arguments this month (a crowd)" if crowd else "")
                              + f" and many badly miss what one gives ({words}): another {kind}"
                              + (f" ({max(want, 1 + cit // cfg['tavern_crowd_per']) if crowd else want} wanted)")))
    return out


# (0.105.29) the customs that place a level of a kind (masterplan.hint applies
# them); the layout ones are customs.LAYOUT. wide_ways and winding_ways bend
# every level's ways: they ride along with these, never call the hint alone.
PLACEMENT_CUSTOMS = {"bedrooms": ("cells",), "dining": ("deep_hall", "field_hall"), "tavern": ("market_gate",),
                     "barracks": ("gate_barracks",), "archery": ("gate_barracks",), "workshops": ("field_kitchens",)}


def apply_customs(action: dict, memory, traits: dict, profile: dict, citizens: int,
                  urgent: bool = False) -> dict | None:
    """(0.105.29) The fort's customs on a start_project: the master plan's hint
    (placement customs; returned, and set as action["plan"]), style.customs
    (layout customs) and action["customs"] (the journal's). The ladder calls it
    as it is; customs_pass with urgent=True for every other rule's level.
    urgent: the level keeps its own placement and gets nothing at all unless a
    custom concerns its kind; the hint is kept only when it applied a placement
    custom of that kind (else the rule's own placement stands)."""
    kind = action["kind"]
    lc = customs.layout_customs(traits, kind)
    place = [c for c in PLACEMENT_CUSTOMS.get(kind, ()) if customs.has(traits, c)] if urgent else None
    where = None
    if memory is not None and (not urgent or place):
        where = masterplan.hint(memory, kind, slot=action.get("set_piece"), traits=traits,
                                profile=profile, action=action, citizens=citizens)
        if urgent and not set(_l((where or {}).get("customs"))) & set(place):
            where = None
    if lc:
        if not isinstance(action.get("style"), dict):
            action["style"] = {}           # (as no style: plain, the bridge's defaults)
        action["style"]["customs"] = lc
    cs = sorted(set(lc) | set(_l((where or {}).get("customs"))))
    if cs:
        action["customs"] = cs
    if where:
        # the door rule follows the fort as it is now (the plan's own was set when it was drawn)
        where["doors"] = ("fortified" if traits.get("fortification", 0) >= 70
                          else "doored" if profile.get("entry_doors") else "open")
        action["plan"] = where                 # the master plan's district for it, tried first
    return where


def customs_pass(proposals: list, memory, traits: dict, citizens: int) -> None:
    """(0.105.29 customs fixes) The fort's customs on every start_project the
    rules proposed without them: the urgent levels of _project_rules and the
    workshop levels of bags, cloth, gems, bottleneck, kiln, glass, industry,
    needs_shops, well_parts, the fishery, moods and bowyers (13 proposers
    that skipped them: no ore_piles on 132 Deep mine workshop levels, no
    field_kitchens). Run once by plan() after every rule has proposed, as
    apply_customs(urgent=True): the hint only when a placement custom of the
    kind is on, kept only when it applied (else the rule's own placement
    stands), the layout customs always. The ladder's level (it has "plan" or
    "customs" from apply_customs already) is left as it is. Nothing at all
    changes for a fort with no custom on. The strategist's levels
    (review.py) get the layout customs only.
    (0.105.33) And the fort's Spacing on every new level whose style has
    none: only the build rule's levels carried it, so 40% of the levels
    (needs_shops, bottleneck, kiln, industry, mood, well_parts, homes_dig,
    petition_build...) ignored the slider. A fort at spacing 0 changes nothing."""
    profile = None
    for p in proposals:
        a = p.action
        if not isinstance(a, dict) or a.get("type") != "start_project" or not isinstance(a.get("kind"), str):
            continue
        style = a.get("style")
        if isinstance(style, dict) and "spacing" in style:
            continue
        if profile is None:
            profile = profile_from(traits, (memory.culture if memory is not None else None) or new_history())
        spacing = int(profile.get("spacing", 0) or 0)
        if spacing:
            p.action = dict(a, style=dict(style if isinstance(style, dict) else {}, spacing=spacing))
    if not customs.active(traits):
        return
    for p in proposals:
        a = p.action
        if not isinstance(a, dict) or a.get("type") != "start_project" or not isinstance(a.get("kind"), str) \
                or "customs" in a or "plan" in a:
            continue
        if profile is None:
            profile = profile_from(traits, (memory.culture if memory is not None else None) or new_history())
        b = dict(a)
        if isinstance(b.get("style"), dict):
            b["style"] = dict(b["style"])      # (a rule's style dict may be shared)
        apply_customs(b, memory, traits, profile, citizens, urgent=True)
        if b != a:
            p.action = b


def _project_rules(s, traits, cfg, proposals, notes, can_use, memory) -> None:
    s.pop("_character_slot", None)          # (0.105.10) this plan's own (normalize may hand back the same dict)
    pr = s["projects"]
    open_ = [p for p in pr.get("open") or [] if isinstance(p, dict)]
    decorating = [p for p in pr.get("decorating") or [] if isinstance(p, dict)]
    history = memory.culture or new_history()
    profile = profile_from(traits, history)
    stone = pick_stone(s.get("stone_types") if isinstance(s.get("stone_types"), list) else [],
                       profile["palette"])
    one_stone = has_rule(memory.culture, "one_stone")                  # (0.103.18) One Stone: its commonest rock
    if one_stone and isinstance(s.get("stone_types"), list) and s["stone_types"] and isinstance(s["stone_types"][0], dict):
        stone = s["stone_types"][0]

    # Move projects along. The game says what's next for each one; older
    # bridges don't, so the phases are also read directly.
    for p in open_ + decorating:
        dig, fur = p.get("dig") or {}, p.get("furnish") or {}
        step = p.get("next")
        if step is None and "next" not in p:
            if p.get("phase") == "dig" and dig.get("total") and dig.get("dug") == dig.get("total"):
                step = "furnish"
            elif p.get("phase") == "furnish" and fur and fur.get("done", 0) == fur.get("placed", 0):
                step = "finish"
        what = f"{p.get('kind')} level #{p.get('id')}"
        if step == "furnish":
            if s["tools"].get("buildingplan") is True:
                left = f" ({dig['stuck']} spots the game cancelled stay rock)" if dig.get("stuck") else ""
                proposals.append(Proposal("project", {"type": "furnish_project", "project_id": p["id"]},
                                          f"{what} is dug out: furnish it{left}", 3))
            else:
                notes.append(f"{what} is dug, waiting for buildingplan to be on")
        elif step == "finish":
            # Includes levels with nothing to build (storage: only stockpiles).
            proposals.append(Proposal("project", {"type": "finish_project", "project_id": p["id"]},
                                      f"{what} is fully built", 3))
        elif step == "cancel":
            action = {"type": "cancel_project", "project_id": p["id"]}
            memorial = (p.get("summary") or {}).get("memorial")
            if memorial:
                action["memorial"] = memorial      # owed again; built elsewhere
            proposals.append(Proposal("project", action,
                                      f"{what}: {dig.get('stuck', 0)} of {dig.get('total', 0)} tiles were "
                                      "cancelled by the game (e.g. damp stone); give up on this spot", 3))
        elif step == "engrave":
            proposals.append(Proposal("project", {"type": "engrave_project", "project_id": p["id"]},
                                      f"{what} is smoothed: engrave its halls", 3))
        elif step != "furnish" and p.get("phase") == "dig" and (dig.get("stuck") or dig.get("marked")):
            if dig.get("marked"):
                # (0.105.35) nothing waits for the player: the AI makes them real (was Needs you)
                proposals.append(Proposal("project", {"type": "unmark_project_dig", "project_id": p["id"]},
                                          f"{what}: {dig['marked']} tiles are designated in marker (blueprint) "
                                          "mode, which dwarves never dig: make them real dig designations", 3))
            if dig.get("stuck"):
                # (0.100.1, overnight run) nothing left being dug and the rest no
                # longer designated: it never finishes, and it held a building
                # slot (with a stuck well, both slots) for five game years while
                # it waited for the player. After STUCK_PROJECT_DAYS it's given up.
                started = stamp_tick(p.get("started"))
                age = (abs_tick(s) - started) // TICKS_PER_DAY if started is not None else None
                if not dig.get("digging") and not dig.get("marked") and age is not None \
                        and age >= cfg["stuck_project_days"]:
                    proposals.append(Proposal("project", {"type": "cancel_project", "project_id": p["id"]},
                                              f"{what}: {dig['stuck']} tiles are no longer designated and nothing "
                                              f"is being dug ({age} days since it started): give it up, so the "
                                              "slot goes to the next level", 3))
                elif not dig.get("marked"):
                    # (0.105.35) said, not Needs you: the AI gives it up itself
                    left = (" once its stalled dig is given up (it has no start date)" if age is None
                            else " once nothing more is being dug" if dig.get("digging")
                            else f" in {max(1, cfg['stuck_project_days'] - age)} day(s)")
                    notes.append(f"{what}: {dig['stuck']} tiles are no longer designated, so it won't finish: "
                                 f"the AI gives it up{left}, so the slot goes to the next level")

    # (0.105.30, construction 3.3) a finished hall's own step `floor`: block
    # floors over its soil (soil can't be smoothed), once per project
    try:
        _soil_floor_rule(s, traits, cfg, proposals, notes, memory)
    except Exception as e:  # noqa: BLE001  (an odd report value: the project steps go on)
        notes.append(f"rule _soil_floor_rule failed ({type(e).__name__}: {str(e)[:120]}); the others ran")
    _dig_stall_rule(s, memory, cfg, open_, proposals, notes)
    _redig_rule(open_, proposals)        # (0.105.48, K7c)

    # (0.104.12) projects that hold a building slot for good: a dig that has
    # crept (under half dug in slow_dig_days: Enxah's cavern well, 2 of 24
    # tiles in six game years) is given up; a level furnished but for statues
    # there's no stone for is finished without them (they stay planned)
    now_ = abs_tick(s)
    for p in open_:
        started = stamp_tick(p.get("started"))
        if started is None:
            continue
        age = (now_ - started) // TICKS_PER_DAY
        dig = _d(p.get("dig"))
        what = f"the {p.get('kind')} level (project {p.get('id')})"
        # (0.105.22) or nothing dug at all in unreached_dig_days: no dwarf gets
        # to it (B's tomb level, 11 times on one stair column, 336 days each,
        # while 41 ghosts rose); its spot is kept off-limits a while (`unreached`)
        # (r2 h8) a landmark's level is not given up at the 56-day mark: its
        # lower levels are reached only down its own stair once the level
        # above is dug, and its levels are designated together (D's Long
        # Descent: levels 43-46 cancelled at 59-67 days, 0 dug, then the whole
        # landmark started again elsewhere, three times; A's chronicle hall
        # twice). It waits h8_landmark_dig_days before it counts as unreached.
        unreached_days, slow_days = cfg["unreached_dig_days"], cfg["slow_dig_days"]
        if p.get("kind") == "landmark":
            lm_days = int(cfg.get("h8_landmark_dig_days", 336))
            unreached_days, slow_days = max(unreached_days, lm_days), max(slow_days, lm_days)
        none_dug = (int(dig.get("dug") or 0) == 0 and age >= unreached_days
                    and int(dig.get("total") or 0) > 0)
        if (p.get("phase") == "dig" and int(dig.get("total") or 0) > 0
                and ((age >= slow_days and int(dig.get("dug") or 0) * 2 < int(dig.get("total") or 0))
                     or none_dug)):
            # (0.105.26) `unreached` (its spot kept off-limits) only where nothing
            # was dug at all: a slow dig was reached, and a cavern well given up
            # as slow stays revivable (lua: revive_cavern_well skips unreached)
            action = {"type": "cancel_project", "project_id": p["id"]}
            if none_dug:
                action["unreached"] = True
            if p.get("kind") == "well" and _d(p.get("summary")).get("cavern"):
                action["cavern_well"] = True
            proposals.append(Proposal("project", action,
                                      f"{what}: {dig.get('dug') or 0} of {dig.get('total')} tiles dug in {age} days: "
                                      "give it up, so its building slot goes to what waits"
                                      + (" (and not that spot again for a while)" if none_dug else ""), 4))
        fw = _d(_d(p.get("furnish")).get("waiting"))
        # (0.104.33) or waits so long for them whatever the stone (Enxah's
        # storage level: 197 days for 1 statue, 199 usable boulders, the
        # mason's bench jammed) while another level is refused for its slot
        fdays = int(_d(p.get("furnish")).get("days") or 0)
        if (p.get("phase") == "furnish" and fw and set(fw) <= {"Statue"}
                and fdays >= cfg["statue_wait_days"]
                and (stone_short(s, cfg["stone_low"]) or fdays >= cfg["statue_wait_days_any"])):
            why = ("there's no stone to carve" if stone_short(s, cfg["stone_low"])
                   else f"they haven't come in {fdays} days")
            proposals.append(Proposal("project", {"type": "finish_project", "project_id": p["id"], "decor_only": True},
                                      f"{what} waits only for {fw.get('Statue')} statue(s) and {why}: "
                                      "finish it (the statues stay planned) and free its slot", 4))
        # (0.105.51) a workshops level waiting only for its workshops' pieces
        # (every R3 fort: Millstones waiting >1000 days for a millstone nobody
        # made, 2-5 of the 5 slots held): given up, the waiting workshops
        # taken off (the paper rule builds a quern instead)
        if (p.get("phase") == "furnish" and fw and set(fw) <= SHOP_KINDS
                and fdays >= cfg["shop_piece_wait_days"]):
            ws = waiting_shops(p)
            kinds = ", ".join(f"{n} {k}" for k, n in sorted(ws.items())) or f"{sum(fw.values())} workshop(s)"
            proposals.append(Proposal("project", {"type": "finish_project", "project_id": p["id"], "give_up": True},
                                      f"{what} has waited {fdays} days for its workshops ({kinds}) to be built: "
                                      "give them up and free its slot", 4))
        # (0.104.141) furnished but for buildings placed and never finished
        # (Teacheroar's 20-bed hospital: 30 of 31 done, nothing missing, 134
        # days) while its slot holds a petition's guildhall back: finish it
        # (DF goes on building what is placed)
        fur = _d(p.get("furnish"))
        if (p.get("phase") == "furnish" and not fw and int(fur.get("placed") or 0) > 0
                and int(fur.get("done") or 0) < int(fur.get("placed") or 0)
                and fdays >= cfg["furnish_stalled_days"]):
            left_ = int(fur.get("placed") or 0) - int(fur.get("done") or 0)
            proposals.append(Proposal("project", {"type": "finish_project", "project_id": p["id"], "stalled": True},
                                      f"{what} has all its furniture and {left_} building(s) placed but not built "
                                      f"in {fdays} days: finish it (DF still builds them) and free its slot", 4))

    # Furniture the projects are waiting for: order what isn't already queued,
    # in the fort's materials: its signature stone, a stone per kind ("by
    # purpose"), or wood where wood will do (while the fort has wood to spare).
    if can_use("orders"):
        stones = s.get("stone_types") if isinstance(s.get("stone_types"), list) else []
        citizens = max(1, s["dwarves"].get("total", 0))
        wood_spare = (s["stocks"].get("wood", 0) or 0) - citizens * cfg["wood_per_dwarf"]
        waiting: dict[str, int] = {}
        for p in open_:
            for kind, n in ((p.get("furnish") or {}).get("waiting") or {}).items():
                waiting[kind] = waiting.get(kind, 0) + int(n or 0)
        # (0.105.51) a planned Quern or Millstone waits for its quern or
        # millstone: ordered at the mason's (not for a level about to be given up)
        pieces: dict[str, int] = {}
        for p in open_:
            if int(_d(p.get("furnish")).get("days") or 0) >= cfg["shop_piece_wait_days"]:
                continue
            for shop, n in waiting_shops(p).items():
                if shop in SHOP_PIECE_RECIPES:
                    pieces[shop] = pieces.get(shop, 0) + n
        for shop, n in sorted(pieces.items()):
            recipe = SHOP_PIECE_RECIPES[shop]
            if n <= 0 or queued(s, {recipe}):
                continue
            why = f"a planned {shop} workshop waits for {SHOP_PIECE_WORDS[shop]} to be built from"
            if stone_short(s, cfg["stone_low"]):
                notes.append(f"{why}: no stone the masons may use")
                continue
            if not _has_shop(s["buildings"], "Masons"):
                notes.append(f"{why}: no Masons' workshop to make it")
                continue
            proposals.append(Proposal("furniture", {"type": "work_order", "recipe": recipe,
                                                    "amount": min(n, cfg["max_order"])},
                                      f"{why}: {min(n, cfg['max_order'])} at the mason's", 3, True))
        for kind, n in sorted(waiting.items()):
            if kind == "Chain":
                _restraint_order(s, n, cfg, proposals, notes)
                continue
            recipe = FURNITURE_RECIPES.get(kind)
            wooden = WOODEN_FURNITURE.get(recipe)
            metal_r = METAL_FURNITURE.get(recipe)
            # (0.104.141) a stone order already made, but too slow for what waits
            # (Teacheroar in crisis: 51 tables and 41 chairs for the dining hall
            # and tavern, 88-93 days, one order each on 5 busy Masons' workshops,
            # 3 carpenters' and 659 logs idle): part of it in wood beside it
            if (recipe and wooden and n > 0 and queued(s, {wooden} | ({metal_r} if metal_r else set())) == 0
                    and _has_shop(s["buildings"], "Carpenters")):
                stone_left = queued(s, {recipe})
                masons = max(1, int(_d(s["buildings"].get("workshops")).get("Masons") or 0))
                part = min(stone_left // 2, n, int(wood_spare) - 2, cfg["max_order"])
                if (stone_left and stone_left / masons >= cfg["furniture_parallel_backlog"]
                        and part >= cfg["furniture_parallel_min"]):
                    proposals.append(Proposal("furniture", {"type": "work_order", "recipe": wooden, "amount": part},
                                              f"building projects are waiting for {n} {kind.lower()}(s) and "
                                              f"{stone_left} in stone wait on {masons} Masons' workshop(s): "
                                              f"{part} in wood beside them at the carpenters'", 3, True))
                    continue
            if recipe and n > 0 and queued(s, {recipe} | ({wooden} if wooden else set())
                                                | ({metal_r} if metal_r else set())) == 0:
                amount = min(n, cfg["max_order"])
                why = f"building projects are waiting for {n} {kind.lower()}(s)"
                metal = spare_metal(s, cfg, amount) if metal_r and (
                    stone_short(s, max(amount, cfg["stone_low"]))
                    or traits.get("craftsmanship", 0) >= 50 or traits.get("grandeur", 0) >= 50
                    # (0.103.11) Forge-born: metal first
                    or (memory is not None and has_rule(memory.culture, "metal_furnish"))) else None
                if metal:
                    action = {"type": "work_order", "recipe": metal_r, "amount": amount, "material": f"INORGANIC:{metal}"}
                    why += f", in {metal.lower().replace('_', ' ')} at the forge (bars the soldiers don't need)"
                elif profile["palette"] == "wood" and wooden and wood_spare >= amount:
                    action = {"type": "work_order", "recipe": wooden, "amount": amount}
                    why += ", in wood (the fort builds in wood where it will do)"
                elif stone_short(s, max(amount, cfg["stone_low"])) and wooden and wood_spare >= amount:
                    action = {"type": "work_order", "recipe": wooden, "amount": amount}
                    why += ", in wood (no stone the masons may use)"
                elif stone_short(s, max(amount, cfg["stone_low"])) and wooden and wood_spare >= 5:
                    # (0.104.138) as many as the wood covers: Teacheroar's 27 coffins
                    # waited with ~20 logs to spare and nothing was ordered at all
                    part = int(wood_spare) - 2
                    action = {"type": "work_order", "recipe": wooden, "amount": part}
                    why += f", {part} of them in wood for now (no stone the masons may use; wood for {part})"
                elif stone_short(s, max(amount, cfg["stone_low"])) and recipe.startswith("stone_"):
                    notes.append(f"{why}: no stone the masons may use" + ("" if wooden else " and no wooden kind"))
                    continue
                else:
                    action = {"type": "work_order", "recipe": recipe, "amount": amount}
                    dz = profile.get("design") if isinstance(profile.get("design"), dict) else {}
                    kstone = (stone_for(stones, profile["palette"], kind,
                                        by_kind=dz.get("by_kind"), signature=dz.get("signature"))
                              if (profile["palette"] == "purpose" or dz.get("by_kind") or dz.get("signature"))
                              and not one_stone else stone)
                    if kstone and recipe.startswith("stone_"):
                        action["material"] = kstone["token"]
                        why += (f", in {kstone.get('name')} (each kind of furniture in its own stone)"
                                if profile["palette"] == "purpose"
                                else f", in the fort's {kstone.get('name') or 'signature'} stone")
                proposals.append(Proposal("furniture", action, why, 3, True))

    # One new level at a time, most urgent need first.
    if traits.get("surface", 0) >= 50:
        notes.append("Surface ambition: the AI builds a walled, roofed keep round the way in (or on open "
                     "ground near the fields); new levels still go underground")
    # (0.100.1, overnight run) a still, a kitchen and a carpenter's workshop
    # before anything else, with a slot of their own (as a farm level has):
    # a fresh fort built a mason's, a mechanic's and the metal works first
    # (for a well and for ore), then both slots stuck, and it never brewed,
    # cooked or made a bed in five years.
    if can_use("stocks") and "buildings" not in s["_errors"]:
        have = {**_d(s["buildings"].get("workshops")), **_d(s["buildings"].get("furnaces"))}
        coming = set()
        for p in open_:
            if p.get("kind") == "workshops":
                coming |= set(_l((p.get("summary") or {}).get("workshops")))
                coming |= set(_d(p.get("furniture")).keys())
        need = [w for w in SURVIVAL_SHOPS if not have.get(w) and w not in coming]
        if need and len(open_) < (pr.get("max_open") or 2) + 1:
            extra = [w for w in BASIC_WORKSHOPS if w not in need and not have.get(w) and w not in coming]
            proposals.append(Proposal("build", {"type": "start_project", "kind": "workshops",
                                                "shops": need + extra, "urgent": True},
                                      f"no {', '.join(need)}: the fort can't brew, cook or make beds, doors and "
                                      "barrels without them; dig them first", 1))
    # (0.100.2, second overnight run) the manager works only in an office: with
    # none, the work orders are never taken up (a fresh fort's brewing, meals,
    # beds and barrels all waited, workshops standing). An office for the
    # manager is a need, not a luxury: one suite, with a slot of its own.
    if can_use("stocks") and "buildings" not in s["_errors"] and manager_needs_office(s) \
            and not any(p.get("kind") == "suites" for p in open_) \
            and len(open_) < (pr.get("max_open") or 2) + 1:
        n_suites = max(1, suites_short(s)) if "office" in noble_room_kinds(traits, memory) else 1
        # (urgent: the builder's extra slot, as for the survival workshops; it
        # holds the open-project limit itself and refused the suite at 2)
        proposals.append(Proposal("build", {"type": "start_project", "kind": "suites", "suites": n_suites,
                                            "urgent": True},
                                  "the manager has no office, and a manager takes up work orders only in one: "
                                  f"dig {'a suite' if n_suites == 1 else f'{n_suites} suites'} (a bedroom and an "
                                  "office each)", 1))
    # (0.104.135, 12k) dining by tables, not halls: Teacheroar had one dining
    # hall and 19 tables for 227 dwarves (a bad thought at every meal eaten
    # without one, in a fort 62% miserable or very unhappy); a second hall
    # came only as the great hall set piece, in good times
    if can_use("stocks") and "buildings" not in s["_errors"] \
            and len(open_) < (pr.get("max_open") or 2) + 2 and not any(p.get("kind") == "dining" for p in open_):
        dn = dining_shortfall(s, cfg)
        if dn and player_rules(s)["levels"].get("dining", True):
            where = " in the dining halls" if dn.get("source") == "public" else ""
            lack = (f"; {dn['lack']} citizens upset at eating without a table this month"
                    if dn.get("lack", 0) >= cfg["lack_tables_min"] else "")
            proposals.append(Proposal("build", {"type": "start_project", "kind": "dining", "tables": dn["tables"],
                                                "urgent": True},
                                      f"{dn['have']} tables{where} for {dn['citizens']} dwarves (the fort wants "
                                      f"{dn['want']}; a meal without one is a bad thought{lack}): another dining "
                                      f"hall with {dn['tables']} tables and chairs", 2))
    # (0.104.137, 12k) taverns and temples by the dwarves who badly miss what
    # they give, not by whether one stands (Teacheroar: 2 taverns and 2
    # temples for 221 dwarves; 85 badly missing friends, 56 drink, 63 prayer)
    if can_use("stocks") and "buildings" not in s["_errors"] and "locations" not in s["_errors"] \
            and len(open_) < (pr.get("max_open") or 2) + 2:
        for kind, cap in social_shortfall(s, cfg):
            if any(p.get("kind") == kind for p in open_) or not player_rules(s)["levels"].get(kind, True):
                continue
            action = {"type": "start_project", "kind": kind, "urgent": True}
            if kind == "tavern":
                action["tables"] = 20
            else:
                # (0.105.23) the bridge knows "shrine" and "grand" only: this temple
                # went without a size and was refused 83 times (fort E, 5 Nov)
                action["size"] = temple_size(traits)
            proposals.append(Proposal("build", action, cap, 2))
            break                                   # one a cycle
    # (0.104.146) a temple to all gods while many pray to gods no temple here
    # serves (Teacheroar: 2 temples, 9 gods prayed to, 93 distracted for want
    # of prayer; more temples by count never came, the count of the badly
    # held at 40 for 2 temples)
    pu = prayer_uncovered(s)
    if (pu and pu[0] >= max(cfg["temple_uncovered_min"], round(cfg["temple_uncovered_share"] * int(_d(s.get("dwarves")).get("total") or 0)))
            and can_use("stocks") and "buildings" not in s["_errors"]
            and len(open_) < (pr.get("max_open") or 2) + 2 and not any(p.get("kind") == "temple" for p in open_)
            and player_rules(s)["levels"].get("temple", True)):
        gods = ", ".join(f"{g} {n}" for g, n in sorted(pu[1].items(), key=lambda kv: -kv[1])[:4])
        proposals.append(Proposal("build", {"type": "start_project", "kind": "temple", "size": "shrine",
                                            "urgent": True},
                                  f"{pu[0]} dwarves are distracted for want of prayer to gods no temple here serves "
                                  f"({gods}): a temple to all gods", 2))
    # (0.104.121) a hospital too small for the fort: Teacheroar's stop-gap of
    # 5 beds (built at 54 dwarves) served 296, 107 on the Rest job, 124
    # patients and 112 infected wounds; "another hospital" was counted by halls (one per 150
    # dwarves) and only in good times. Counted by beds against the wounded
    # resting, in bad times too (a second hospital brings 4 more posts), with a slot of its own.
    generous = None   # (0.105.113) Welfare's extra hospital, the season's build only if none other
    if can_use("stocks") and "buildings" not in s["_errors"] and "locations" not in s["_errors"] \
            and len(open_) < (pr.get("max_open") or 2) + 2 and not any(p.get("kind") == "hospital" for p in open_):
        hp = hospital_shortfall(s, traits, cfg)
        if hp and hp.get("generous") and player_rules(s)["levels"].get("hospital", True):
            # (0.105.113 item11) Welfare's generosity: no slot of its own, after the
            # needs (the wounded's case above keeps its urgent slot)
            # (0.105.113) the season's one build: proposed at the end only when no other level is
            if len(open_) < (pr.get("max_open") or 2) and settled_times(s, memory, traits, cfg):
                generous = (Proposal("build", {"type": "start_project", "kind": "hospital", "beds": hp["beds"]},
                                          f"Welfare {int(traits.get('welfare', 0) or 0):+d}: the hospitals have "
                                          f"{hp['have']} beds for {hp['citizens']} dwarves and a caring fort keeps "
                                          f"{hp['want']}: another hospital with {hp['beds']} beds", 5))
        elif hp and player_rules(s)["levels"].get("hospital", True):
            proposals.append(Proposal("build", {"type": "start_project", "kind": "hospital", "beds": hp["beds"],
                                                "urgent": True},
                                      f"{hp['resting']} wounded dwarves resting and the hospitals have "
                                      f"{hp['have']} beds for {hp['citizens']} dwarves (the fort wants {hp['want']}): "
                                      f"another hospital with {hp['beds']} beds", 1))
    # (0.103.8) dwarves waiting for care with no hospital: a hospital with a
    # slot of its own (Enxah: the chief medical dwarf waited 252 days, 4
    # infected wounds, while a tomb level and a workshops level held both slots)
    if can_use("stocks") and "buildings" not in s["_errors"] and "locations" not in s["_errors"] \
            and len(open_) < (pr.get("max_open") or 2) + 2 and len(open_) >= (pr.get("max_open") or 2):
        waiting = care_waiting(s)
        cit = max(1, int(_d(s.get("dwarves")).get("total") or 0))
        locs = _d(_d(s.get("locations")).get("count"))
        if (waiting >= cfg["urgent_hospital_waiting"] and cit >= cfg["min_dwarves_for_small_hospital"]
                and player_rules(s)["levels"].get("hospital", True) and not locs.get("HOSPITAL")
                and not any(p.get("kind") == "hospital" for p in open_)):
            beds = max(4, min(20, math.ceil(cit / 20 * factor(traits, "welfare")) + 2))
            proposals.append(Proposal("build", {"type": "start_project", "kind": "hospital", "beds": beds,
                                                "urgent": True},
                                      f"{waiting} dwarves wait for care and there is no hospital: build one with "
                                      f"{beds} beds now, ahead of the levels under way", 1))
        # (0.103.12) most of the fort longing to pray with only the stop-gap
        # temple over the dining hall: a shrine with a slot of its own (Enxah,
        # 49 dwarves: 53 prayers unmet, 13 miserable, every slot on bedrooms,
        # a well and tombs)
        lc = _d(_d(s.get("locations")).get("count"))
        pray = unmet(s, "PrayOrMeditate")
        share = cfg["urgent_temple_share"] / (2 if memory is not None and has_rule(memory.culture, "omens") else 1)
        if (pray >= max(cfg["needs_build_at"], math.ceil(cit * share))      # (0.103.17) Superstitious: a quarter
                and player_rules(s)["levels"].get("temple", True) and player_rules(s)["fort_goal"] != "maintain"
                and not _real_locations(lc, "TEMPLE", memory, _l(_d(s.get("locations")).get("list")))
                and not any(p.get("kind") == "temple" for p in open_)
                and not any(x.action.get("kind") == "hospital" and x.action.get("urgent") for x in proposals)):
            proposals.append(Proposal("build", {"type": "start_project", "kind": "temple", "size": "shrine",
                                                "urgent": True},
                                      f"{min(pray, cit)} dwarves are distracted for want of somewhere to pray and the fort "
                                      "has only the dining hall for it: dig a shrine now, ahead of the levels under way", 1))
        # (0.104.12) the dead unburied (ghosts, or many bodies: seeing them
        # stresses the living) with both slots taken: a tomb level of its own
        # slot. It was looked at only after the "slots full" return below, so
        # it never came when it was needed (Enxah y60: 35 unburied, 4 ghosts,
        # 7 free tombs, the slots on a stuck well and suites)
        dead = _d(s.get("dead"))
        if (player_rules(s)["levels"].get("tombs", True)
                and ((dead.get("ghosts") or 0) > 0 or (dead.get("unburied") or 0) >= cfg["urgent_unburied"])
                and not any(p.get("kind") == "tombs" for p in open_)
                and tombs_short(s, cit, cfg, memory) > 0
                and not any(x.action.get("urgent") and x.action.get("kind") in ("hospital", "temple") for x in proposals)):
            short = tombs_short(s, cit, cfg, memory) + (dead.get("ghosts") or 0)
            coffins = max(4, min(30, short * 2))
            proposals.append(Proposal("tombs_ghosts", {"type": "start_project", "kind": "tombs", "coffins": coffins,
                                                       "urgent": True, "style": layout_style(profile, "tombs")},
                                      f"{dead.get('unburied') or 0} dead unburied, {dead.get('ghosts') or 0} ghost(s) and "
                                      f"{dead.get('free_tombs', 0)} free tombs: dig a tomb level with {coffins} coffins "
                                      "now, ahead of the levels under way", 2))
        # (0.104.31) tantrums are crimes: with a sheriff or captain and no jail
        # the punishment is a beating, and the beaten fill the hospital (Enxah:
        # one bone carver's tantrums 194 times in the log, 18 abed). A jail
        # with an urgent slot of its own while tantrums come thick
        tn = tantrums_recent(s, memory)
        jp = jail_plan(traits, cfg, cit)
        if (tn >= cfg["urgent_jail_tantrums"] and jp and justice_held(s)
                and player_rules(s)["levels"].get("jail", True)
                and _d(_d(s.get("buildings")).get("zones")).get("Dungeon", 0) == 0
                and not any(p.get("kind") == "jail" for p in open_)
                and not any(x.action.get("urgent") and x.action.get("kind") in ("hospital", "temple", "tombs")
                            for x in proposals)):
            proposals.append(Proposal("jail_urgent", {"type": "start_project", "kind": "jail", "cells": jp["cells"],
                                                      "urgent": True},
                                      f"{tn} tantrums in 28 days and no jail: the guard beats the offenders and the beaten "
                                      f"fill the hospital: dig a jail with {jp['cells']} cells now", 2))
        # (0.104.35) a third of the fort badly wanting company with only the
        # stop-gap tavern over the dining hall: a proper tavern with a slot of
        # its own (Enxah, spring y64: 38 of 71 badly, 56 distracted, tantrums
        # and their beatings putting 27 to bed; the ladder's tavern never got
        # a slot behind tombs, storage and the jail)
        friends = int(_d(_d(_d(s.get("needs")).get("needs")).get("BeWithFriends")).get("badly") or 0)
        if (friends >= max(cfg["needs_build_at"], math.ceil(cit * cfg["urgent_tavern_share"]))
                and player_rules(s)["levels"].get("tavern", True) and player_rules(s)["fort_goal"] != "maintain"
                and not _real_locations(lc, "INN_TAVERN", memory, _l(_d(s.get("locations")).get("list")))
                and not any(p.get("kind") == "tavern" for p in open_)
                and not any(x.action.get("urgent") and x.action.get("kind") in ("hospital", "temple", "tombs", "jail")
                            for x in proposals)):
            tables = max(4, min(20, math.ceil(cit / 10 * tavern_factor(traits))))
            proposals.append(Proposal("tavern_urgent", {"type": "start_project", "kind": "tavern", "tables": tables,
                                                        "urgent": True},
                                      f"{friends} dwarves badly want time with friends and the fort has only the dining "
                                      f"hall for a tavern: dig a tavern with {tables} tables now, ahead of the levels "
                                      "under way", 2))
    if len(open_) >= (pr.get("max_open") or 2) or not can_use("stocks") or "buildings" in s["_errors"]:
        return
    kinds_open = {p.get("kind") for p in open_}
    lb = _d(s.get("labor"))
    if "dig" in lb and lb.get("dig", 0) > max(1, lb.get("miners") or 0) * cfg["dig_backlog_per_miner"]:
        notes.append(f"no new level yet: {lb['dig']} tile(s) wait to be dug by {lb.get('miners') or 0} miner(s)")
        return
    b = s["buildings"]
    other, zones, shops = b.get("other") or {}, b.get("zones") or {}, b.get("workshops") or {}
    loc = s.get("locations") if isinstance(s.get("locations"), dict) else {}
    locations = loc.get("count") if isinstance(loc.get("count"), dict) else {}
    citizens = max(1, s["dwarves"].get("total", 0))
    action, reason = None, ""
    allow = dict(player_rules(s)["levels"])
    if mining_plan(traits, cfg)["need_only"]:
        # (0.96) Mining -100: only the levels the fort needs (was: none at all)
        for kind in MINING_NEED_ONLY:
            if allow.get(kind, True):
                allow[kind] = False
        notes.append("Mining -100: only the levels the fort needs (no library, archery, garden, barracks, "
                     "temple or jail level)")
    # kinds you've turned down wait (or are left to you); the next kind gets its turn
    held = held_levels(memory, abs_tick(s)) if memory is not None else {}
    if memory is not None:
        for kind, why in phases.held_kinds(memory, abs_tick(s)).items():   # the fort's phase of life
            held.setdefault(kind, why)
    for kind, why in held.items():
        if allow.get(kind, True):        # (a kind already switched off in the Rules tab says nothing)
            allow[kind] = False
            notes.append(why)

    young = young_fort(s, cfg)
    beds = other.get("Bed", 0)
    # Beds of levels still being dug; once furnishing starts, the (planned) beds
    # are buildings and already in the bed count.
    planned_beds = sum((p.get("summary") or {}).get("beds", 0) for p in open_
                       if p.get("kind") == "bedrooms" and p.get("phase") == "dig")
    goal = player_rules(s)["fort_goal"]
    if goal == "maintain":
        want_beds = citizens + cfg["maintain_spare_beds"]
    else:
        want_beds = citizens + max(cfg["min_spare_beds"], math.ceil(citizens * cfg["spare_beds_share"]))
        target = growth_target(s, cfg)
        if target > citizens and not young:   # room for the migrants the fort is growing toward
            want_beds = max(want_beds, min(target, citizens + cfg["beds_ahead"]))
        if memory is not None and has_rule(memory.culture, "rooms_ahead"):
            # (0.103.6) Cradle-hold: a room ready for every child, and some
            want_beds += int(_d(s.get("dwarves")).get("children") or 0) + cfg["min_spare_beds"]
    fresh_shops = not any(shops.get(w) for w in BASIC_WORKSHOPS) and beds == 0   # (a new fort: nothing built yet)
    if fresh_shops and "workshops" not in kinds_open:
        # a new fort: workshops first (beds, tables and doors all come from them)
        action = {"type": "start_project", "kind": "workshops", "shops": list(BASIC_WORKSHOPS)}
        reason = "a new fort with no workshops: dig the basic ones first (the furniture comes from them)"
    elif fresh_shops and b.get("stockpiles", 0) == 0 and "storage" not in kinds_open:
        small = memory is not None and (has_rule(memory.culture, "small_rooms") or has_rule(memory.culture, "small_storage"))
        action = {"type": "start_project", "kind": "storage", "piles": BASIC_STOCKPILES, "room_size": 5 if small else 7}
        reason = "a new fort with no stockpiles: dig a storage level for the wagon's goods"
    elif (young and _d(s.get("labor")).get("fish_water") and not shops.get("Fishery")
          and "workshops" not in kinds_open):
        # fish are caught raw: a fishery cleans them for the kitchen
        action = {"type": "start_project", "kind": "workshops", "shops": ["Fishery", "Butchers"]}
        reason = "water to fish in and no fishery: dig one (with a butcher's shop) so the catch can be eaten"
    elif beds + planned_beds < want_beds and "bedrooms" not in kinds_open:
        rooms = min(32, want_beds - beds - planned_beds)
        size = room_size(traits)
        if memory is not None and has_rule(memory.culture, "small_rooms"):
            size = max(2, size - 1)                  # Warren: small rooms
        if young:
            size = 2                                 # a young fort: a bed and a door, quick to dig
        action = {"type": "start_project", "kind": "bedrooms", "rooms": rooms, "room_size": size}
        reason = f"{beds} beds for {citizens} dwarves: dig {rooms} bedrooms"
        if memory is not None and has_rule(memory.culture, "dormitories"):
            # (0.103.11) Communal: one hall of beds, a chest by each
            rooms = max(4, min(20, rooms))
            action = {"type": "start_project", "kind": "bedrooms", "rooms": rooms, "room_size": 2,
                      "dormitory": True}
            reason = f"{beds} beds for {citizens} dwarves: dig a dormitory of {rooms} beds (a communal fort)"
    elif (zones.get("DiningHall", 0) == 0 and citizens >= cfg["min_dwarves_for_dining"]
          and "dining" not in kinds_open):
        tables = max(4, min(90, math.ceil(citizens / cfg["dwarves_per_table"])))
        action = {"type": "start_project", "kind": "dining", "tables": tables}
        reason = f"no dining hall for {citizens} dwarves: dig one with {tables} tables"
    elif "workshops" not in kinds_open and [w for w in BASIC_WORKSHOPS if not shops.get(w)]:
        missing = [w for w in BASIC_WORKSHOPS if not shops.get(w)]
        action = {"type": "start_project", "kind": "workshops", "shops": missing}
        reason = "missing basic workshops: " + ", ".join(missing)
    elif (allow["tombs"] and tombs_short(s, citizens, cfg, memory) > 0 and "tombs" not in kinds_open
          # (0.104.37) not beside the urgent tomb level of this same cycle
          # (Enxah, 02:13: both went through, two tomb levels at once)
          and not any(x.action.get("kind") == "tombs" and x.action.get("urgent") for x in proposals)):
        short = tombs_short(s, citizens, cfg, memory)
        coffins = max(4, min(30, short * 2))
        action = {"type": "start_project", "kind": "tombs", "coffins": coffins}
        reason = (f"{_d(s.get('dead')).get('free_tombs', 0)} free tombs"
                  + (f" and {_d(s.get('dead')).get('unburied')} bodies to bury" if _d(s.get('dead')).get('unburied') else "")
                  + f": dig a tomb level with {coffins} coffins (unburied dead come back as ghosts)")
    elif b.get("stockpiles", 0) == 0 and "storage" not in kinds_open:
        small = memory is not None and (has_rule(memory.culture, "small_rooms") or has_rule(memory.culture, "small_storage"))
        action = {"type": "start_project", "kind": "storage", "piles": BASIC_STOCKPILES, "room_size": 5 if small else 7}
        reason = "no stockpiles: dig a storage level"
    elif ("storage" not in kinds_open and full_stores(s, cfg)
          # (0.104.38) one storage level for full piles a season and a half
          # at most: Enxah's overnight run dug 35 in six game years, the
          # crafts and quarried stone filling each as it was finished
          and not (memory is not None and isinstance(memory.storage_started, int)
                   and 0 <= abs_tick(s) - memory.storage_started < cfg["storage_gap_days"] * TICKS_PER_DAY)):
        kinds = full_stores(s, cfg)
        small = memory is not None and (has_rule(memory.culture, "small_rooms") or has_rule(memory.culture, "small_storage"))
        action = {"type": "start_project", "kind": "storage", "piles": kinds[:4], "room_size": 5 if small else 7}
        st = _d(_d(s.get("logistics")).get("storage"))
        reason = ("stockpiles full, things lying about: " + "; ".join(
            f"{k.replace('_', ' ')} {_d(st.get(k)).get('used')}/{_d(st.get(k)).get('tiles')} tiles used, "
            f"{_d(st.get(k)).get('loose')} loose" for k in kinds[:4]) + ": dig more storage for them")
    elif (allow["hospital"] and "hospital" not in kinds_open
          and (citizens >= cfg["min_dwarves_for_hospital"]
               or (not young and citizens >= cfg["min_dwarves_for_small_hospital"] and _office_held(s, "CHIEF_MEDICAL_DWARF"))
               # (0.102.3) dwarves waiting for care, young fort or not (Enxah:
               # 4 infected wounds, no hospital, the doctor himself a patient)
               or (citizens >= cfg["min_dwarves_for_small_hospital"] and care_waiting(s) >= 2))
          and "locations" not in s["_errors"] and not locations.get("HOSPITAL")):
        beds = max(4, min(20, math.ceil(citizens / 20 * factor(traits, "welfare")) + 2))
        action = {"type": "start_project", "kind": "hospital", "beds": beds}
        reason = f"no hospital for {citizens} dwarves: build one with {beds} beds"
    # (0.98) The weighted ladder: once the levels the fort needs to live are
    # dealt with (above: workshops, storage, bedrooms, dining, tombs,
    # hospital), every optional level whose time has come is a candidate,
    # scored by its old place in the ladder, the temperament and the need
    # (ladder_score); the best goes first. Neutral sliders keep the old order.
    cands: list = []
    # (0.105.10, 14.1 step 3) the fort's own levels are weighed every cycle,
    # not only once every need is met: one building slot is theirs
    need_action, need_reason = action, reason
    action, reason = None, ""
    if True:
        if (allow["jail"] and not young and jail_plan(traits, cfg, citizens)
              and citizens >= jail_plan(traits, cfg, citizens)["min_dwarves"] and justice_held(s)
              and zones.get("Dungeon", 0) == 0 and "jail" not in kinds_open):
            cells = jail_plan(traits, cfg, citizens)["cells"]
            action = {"type": "start_project", "kind": "jail", "cells": cells}
            reason = (f"the fort has a sheriff and no jail: dig {cells} cells with restraints (convicts are "
                      "chained there; without a jail, justice is beatings or nothing)"
                      + (f"; Justice {int(traits.get('justice', 0)):+d}" if traits.get("justice") else ""))
            cands.append((action, reason))
            action, reason = None, ""
        if ("suites" not in kinds_open and suites_short(s) > 0 and not manager_needs_office(s)
              and (not young or traits.get("deference", 0) >= 50
                   or (memory is not None and has_rule(memory.culture, "noble_pride")))
              and "office" in noble_room_kinds(traits, memory)):
            n = suites_short(s)
            action = {"type": "start_project", "kind": "suites", "suites": n}
            reason = (f"{n} noble{'s' if n > 1 else ''} without the rooms their office asks for and none free: "
                      f"dig {n} suite{'s' if n > 1 else ''} (a bedroom and an office each)")
            cands.append((action, reason))
            action, reason = None, ""
        if (allow["tavern"] and (citizens >= cfg["min_dwarves_for_tavern"]
                                   or (citizens >= 8 and unmet(s, *SOCIAL_NEEDS) >= cfg["needs_build_at"]))
              and "tavern" not in kinds_open
              and "locations" not in s["_errors"] and not _real_locations(locations, "INN_TAVERN", memory, _l(loc.get("list")))):
            tables = max(4, min(20, math.ceil(citizens / 10 * tavern_factor(traits))))
            action = {"type": "start_project", "kind": "tavern", "tables": tables}
            reason = f"no tavern for {citizens} dwarves (they need to socialise and drink together): build one" + (
                f"; {unmet(s, *SOCIAL_NEEDS)} are distracted for want of company or a drink"
                if unmet(s, *SOCIAL_NEEDS) else "")
            cands.append((action, reason))
            action, reason = None, ""
        if (allow["library"] and goal != "maintain"
              and (citizens >= cfg["min_dwarves_for_library"]
                   or (citizens >= 8 and unmet(s, *LEARNING_NEEDS) >= cfg["needs_build_at"]))
              and "library" not in kinds_open
              and "locations" not in s["_errors"]
              and (not locations.get("LIBRARY")
                   # (0.103.2) a Scholars' Hold of 40+ raises a second
                   or (memory is not None and has_rule(memory.culture, "library_first")
                       and citizens >= 40 and int(locations.get("LIBRARY") or 0) < 2))):
            action = {"type": "start_project", "kind": "library", "bookcases": 6}
            reason = f"no library for {citizens} dwarves (scholars and curious dwarves need one): build one"
            cands.append((action, reason))
            action, reason = None, ""
        if (allow["barracks"] and barracks_wanted(s, traits, memory)
              and not zones.get("Barracks")
              and "barracks" not in kinds_open):
            beds = max(4, min(20, math.ceil(citizens / 10 * factor(traits, "militarism") / 2)))
            action = {"type": "start_project", "kind": "barracks", "beds": beds}
            reason = f"a militant fort without barracks: build one for {beds} soldiers"
            cands.append((action, reason))
            action, reason = None, ""
        if (allow.get("archery", True) and any(is_ranged(q) and (q.get("members") or 0) > 0
                                                  for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict))
              and not zones.get("ArcheryRange") and "archery" not in kinds_open):
            n = sum(int(q.get("members") or 0) for q in _l(_d(s.get("military")).get("squads"))
                    if isinstance(q, dict) and is_ranged(q))
            lanes = max(1, min(3, -(-n // 4)))
            action = {"type": "start_project", "kind": "archery", "lanes": lanes, "length": 12}
            reason = f"a crossbow squad of {n} and no archery range: dig one with {lanes} target(s)"
        # Culture: memorials for slain beasts, then a temple for a devout fort.
            cands.append((action, reason))
            action, reason = None, ""
        if (profile["memorials"] and "memorial" not in kinds_open and goal != "maintain"
              and "memorial" not in held and memorial_due(s, memory, player_rules(s))):
            name = profile["memorials"][0]
            action = {"type": "start_project", "kind": "memorial", "name": name}
            reason = f"{name} was slain: build a memorial hall"
            cands.append((action, reason))
            action, reason = None, ""
        if (allow["temple"] and goal != "maintain"
              and (profile["temple"] != "none" or unmet(s, "PrayOrMeditate") >= cfg["needs_build_at"])
              and "temple" not in kinds_open
              and "locations" not in s["_errors"] and not _real_locations(locations, "TEMPLE", memory, _l(loc.get("list")))):
            size = profile["temple"] if profile["temple"] != "none" else "shrine"
            action = {"type": "start_project", "kind": "temple", "size": size}
            reason = (f"the fort is devout and has no temple: build a {size}" if profile["temple"] != "none" else
                      f"{unmet(s, 'PrayOrMeditate')} dwarves are distracted for want of somewhere to pray: build a shrine")
        # Set pieces: in good times, a statue garden named for the fort
            cands.append((action, reason))
            action, reason = None, ""
        # (0.102.1) a devout fort that has its temple raises one to each god
        # many of its dwarves long to pray to (Piety 150 built nothing in the
        # Monastery run: a mature fort saw nothing missing)
        more = more_temple(s, traits, cfg) if (allow["temple"] and goal != "maintain" and "temple" not in kinds_open
                                               and locations.get("TEMPLE")) else None
        if more:
            god, hf, n = more
            # (0.103.12) the bridge knows "shrine" and "grand" only: "temple" was refused
            size = temple_size(traits)
            cands.append(({"type": "start_project", "kind": "temple", "size": size, "deity_hf": hf},
                          f"a devout fort (Piety {int(traits.get('piety', 0)):+d}): {n} dwarves "
                          + ("long to pray to" if n <= int(_d(_d(s.get("needs")).get("deities")).get(god) or 0)
                             else "pray to")
                          + f" {god}, who has no temple here: raise one"))
        # (0.105.23, 14.1 step 4b) a fort this devout has a grand temple: when
        # no god asks for one of its own, a grand temple to all gods (B's
        # first was a shrine dug urgently; the ladder's grand one never came)
        elif (allow["temple"] and goal != "maintain" and "temple" not in kinds_open
              and (traits.get("piety", 0) or 0) >= cfg["temple_grand_piety"]
              and "locations" not in s["_errors"]
              and _real_locations(locations, "TEMPLE", memory, _l(loc.get("list")))
              and int(locations.get("TEMPLE") or 0) < 1 + int((traits.get("piety", 0) or 0) // 50)
              and not has_grand_temple(s, memory)):
            cands.append(({"type": "start_project", "kind": "temple", "size": "grand"},
                          f"a devout fort (Piety {int(traits.get('piety', 0)):+d}) with no grand temple: "
                          "raise a grand temple to all gods"))
        if (allow.get("garden", True) and goal != "maintain" and "garden" not in kinds_open
              and memory is not None
              and good_times(s, memory, traits, cfg, pace=garden_pace(traits, cfg))):   # (0.105.47) sooner by Agriculture
            name = garden_name(s, memory)
            action = {"type": "start_project", "kind": "garden", "name": name}
            reason = (f"good times (fed, safe, {round(100 * _idle_share(s))}% idle): dig a statue garden, "
                      f"The {name} Garden, for the fort to be proud of")
            cands.append((action, reason))
            action, reason = None, ""
        # the plan's great hall, a set piece (0.98): a grand dining hall in
        # the halls district, in good times, once the fort has outgrown its first
        if (memory is not None and goal != "maintain" and zones.get("DiningHall", 0) >= 1
                and "dining" not in kinds_open and citizens >= cfg["great_hall_min_citizens"]
                and masterplan.open_slot(memory, "great hall") and good_times(s, memory, traits, cfg)):
            tables = max(20, min(90, citizens // 2))
            cands.append(({"type": "start_project", "kind": "dining", "tables": tables, "set_piece": "great hall"},
                          f"good times and {citizens} dwarves: raise the plan's great hall, a dining hall of "
                          f"{tables} tables among the halls"))
        # (0.104.85) a mature fort keeps growing its character: a second (and
        # further) tavern, library, hospital or barracks as the fort grows,
        # sooner as the sliders care (the 14.1 exit test: two forts of opposite
        # sliders built the same 20 levels; Enxah: 20 finished, none open)
        if memory is not None and goal != "maintain" and not young:
            cands.extend(growth_candidates(s, traits, cfg, memory, allow, kinds_open, locations, zones, citizens))
            # (0.105.23) a grand temple grown with the fort is the grand temple: not two
            if any(c[0].get("growth") and c[0].get("kind") == "temple" and c[0].get("size") == "grand" for c in cands):
                cands = [c for c in cands if not (c[0].get("kind") == "temple" and c[0].get("size") == "grand"
                                                  and not c[0].get("growth") and "deity_hf" not in c[0])]
        action, reason = need_action, need_reason
        if cands:
            scored = sorted(cands, key=lambda c: -ladder_score(c[0], s, traits, cfg, memory))
            reserved = character_slot_reserved(s, traits, cfg, memory, open_)
            if reserved and memory is not None:
                # (0.105.10 review) a level the game keeps refusing never holds the slot
                now_r = abs_tick(s)
                scored = [c for c in scored if _refused_wait(memory, Proposal("build", c[0], c[1], 6), now_r,
                                                             s.get("bridge_version")) is None] or scored
                if all(_refused_wait(memory, Proposal("build", c[0], c[1], 6), now_r, s.get("bridge_version"))
                       is not None for c in scored):
                    reserved = None
            # (0.105.23, 14.1 step 4b) the Monastery's bend: before the basics
            # are met, a devout fort's last slot may go to a shrine (only a
            # temple, shrine-sized: quick to dig, the food and drink still short)
            if not reserved:
                bend = piety_slot(s, traits, cfg, memory, open_)
                temples = [c for c in scored if c[0].get("kind") == "temple"] if bend else []
                if memory is not None:
                    now_r = abs_tick(s)
                    temples = [c for c in temples if _refused_wait(
                        memory, Proposal("build", dict(c[0], size="shrine"), c[1], 6), now_r,
                        s.get("bridge_version")) is None]
                if temples:
                    scored = [(dict(c[0], size="shrine"),
                               c[1].replace("grand temple", "shrine").replace("build a grand", "build a shrine")
                               + " (a shrine for now: the food and drink aren't all there yet)")
                              for c in temples]
                    reserved = bend
            # (review) care comes first: tombs and a hospital aren't put off
            if reserved and action is not None and action.get("kind") in ("tombs", "hospital"):
                reserved = None
            if len(scored) > 1 and (action is None or reserved):
                notes.append("next level by the fort's temperament: " + ", ".join(
                    f"{_ladder_word(c[0])} {ladder_score(c[0], s, traits, cfg, memory):.1f}" for c in scored[:4]))
            if action is None:
                action, reason = scored[0]
            elif reserved:
                notes.append(f"the last building slot is the fort's own ({reserved}): the "
                             f"{_ladder_word(scored[0][0])} level goes ahead of the {action.get('kind')} level")
                action, reason = scored[0]
                reason += " (the fort's own building slot)"
            if reserved:
                s["_character_slot"] = {"why": reserved, "kind": _ladder_word(scored[0][0])}
    rules_ = player_rules(s)
    if profile["memorials"] and "memorial" not in kinds_open and not memorial_due(s, memory, rules_):
        notes.append(f"memorial for {profile['memorials'][0]} waits: "
                     + ("memorials are switched off in the Rules tab" if rules_["memorial_pace"] == "never"
                        else f"at most one per {rules_['memorial_pace']} (Rules tab)"))
    if action and young and action["kind"] not in ("workshops", "storage", "farms", "tombs"):
        fpd = food_per_dwarf(s)
        if not has_farms(s) and fpd < cfg["found_food_per_dwarf"]:
            notes.append(f"food first: {fpd:g} food a dwarf and no farm yet, so the {action['kind']} level waits "
                         "(the dwarves gather, fish and farm instead)")
            action = None
    # (0.105.26) the ghosts' own tomb level is proposed once, with the urgent
    # levels above (tombs_ghosts); a second copy here proposed it again
    if action:
        action["style"] = layout_style(profile, action["kind"])
        if memory is not None and has_rule(memory.culture, "doored_levels"):
            action["style"]["entry_door"] = True    # (0.103.1, Sealed Halls: the rule had no effect)
        if memory is not None:
            action["style"].update(masterplan.variety(memory, action["kind"]))   # seeded details
        if young:
            action["style"].update(smooth=0, statues=0)    # a young fort builds plain: smoothing and statues later
        where = apply_customs(action, memory, traits, profile, citizens)   # the plan's hint, the customs
        if where:
            reason += f" (in {where['district']})"
        proposals.append(Proposal("build", action, reason, 6))
    elif generous is not None and not any(x.rule == "build" and x.action.get("type") == "start_project"
                                          for x in proposals):
        proposals.append(generous)


def temple_size(traits: dict) -> str:
    """(0.105.23) The size of a temple the bridge takes ("shrine" or "grand"):
    grand at Piety +100 and up."""
    return "grand" if (traits.get("piety", 0) or 0) >= 100 else "shrine"


# --- (0.104.85) the fort keeps growing its character ----------------------------------


