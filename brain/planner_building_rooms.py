"""planner_building_rooms: the rooms the projects rule weighs (stairwell, deep
notes, gardens, prayer, dining, hospital, barracks, temples, tombs), the
dig stalls and redigs, room sizes and the placement customs (split out of
planner_building in r7 d4, moved unchanged). planner_building keeps
_project_rules, social_shortfall and temple_size (patched there by tests)
and re-exports every name here."""

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

__all__ = ["_stairwell_rule", "_deep_notes", "ORDINALS", "garden_name", "SOCIAL_KINDS", "prayer_uncovered", "dining_shortfall", "hospital_shortfall", "DIG_FIRST_KINDS", "WELL_DIG_ASK", "_well_dig_rule", "_dig_stall_rule", "_redig_rule", "barracks_wanted", "room_size", "PLACEMENT_CUSTOMS", "apply_customs", "customs_pass", "more_temple", "has_grand_temple", "tombs_short"]


def _stairwell_rule(s: dict, memory, cfg: dict, traits: dict, proposals: list) -> None:
    """(0.104.82) Stairwells, as the fort's style asks (the Stairwells area:
    one great stair, a second one, or one a district; The Hundred Stairs two
    more): while the survey counts fewer, a new one for the next district of
    the plan without one, `dir` of the main stair, from the district's top
    down through its levels. A season apart (the survey counts again)."""
    if memory is None or young_fort(s, cfg):
        return
    if int(_d(s.get("dwarves")).get("total") or 0) < cfg["stairwell_min_citizens"]:
        return
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return
    site = _d(_d(_d(memory.atlas).get("survey")).get("site"))
    have = site.get("stairwells")
    if not isinstance(have, int):
        return                                  # an older bridge's survey: nothing counted
    try:
        want = int(profile_from(traits, memory.culture).get("stairwells") or 1)
    except (TypeError, ValueError):
        want = 1
    if has_rule(_d(memory.culture), "many_stairs"):
        want += 2
    if have >= want:
        return
    d = masterplan.stairwell_district(memory)
    if not d:
        return
    plan = _d(_d(memory.atlas).get("plan"))
    spine = _d(plan.get("spine"))
    dirs = [x for x in d.get("dirs") or [] if x in masterplan.DIRS]
    action = {"type": "dig_stairwell", "dir": dirs[0], "elev_lo": int(d["lo"]), "elev_hi": int(d["hi"]),
              "district": d.get("id")}
    if isinstance(spine.get("x"), int) and isinstance(spine.get("y"), int):
        action["spine"] = {"x": spine["x"], "y": spine["y"]}
    proposals.append(Proposal("stairwell", action,
                              f"the fort's style asks for {want} stairwell(s) and it has {have}: a new one "
                              f"{dirs[0]} of the main stair for {d.get('name') or d.get('id')} "
                              f"(elevations {d['lo']}-{d['hi']}), its levels to grow from it", 6))


def _deep_notes(s: dict, notes: list) -> None:
    """The deep (the bridge's `deep` report): caverns found and whether the
    fort's ground joins them, great dangers on the map and where, cursed
    citizens. (0.105.35) Said, with what the AI does about each: the cavern
    seal, the moon cells and sending vampires away are its own rules
    (planner_threats, planner_military); a Rules switch off is the player's."""
    d = s.get("deep")
    if not isinstance(d, dict) or "error" in d:
        return
    caverns = [c for c in _l(d.get("caverns")) if isinstance(c, dict)]
    open_ = [c for c in caverns if c.get("discovered") and c.get("open")]
    dangers = [x for x in _l(d.get("dangers")) if isinstance(x, dict) and not x.get("caged")]
    for c in open_:
        at = _d(c.get("open_at"))                   # (0.104.101) where the dwarves' ground meets it
        where_ = f" (the dwarves' ground meets it at x{at.get('x')} y{at.get('y')} z{at.get('z')})" if at else ""
        here = [x for x in dangers if x.get("layer") == c.get("name")]
        if here:
            # (0.105.35 merge) the threats rule's own test (planner_threats
            # _cavern_beasts: seal_cavern on every way down, the cavern doors)
            from planner_threats import cavern_great
            great = [x for x in cavern_great(s) if x in here]
            if great:
                here = great + [x for x in here if x not in great]
            seal = _d(s.get("settings")).get("seal_caverns") is not False and bool(great)
            notes.append(f"{c['name']} is open to the fort{where_} and {here[0].get('name')} ({here[0].get('kind')}) "
                         "is in it: " + ("the AI locks every way into the caverns while it's there (doors and "
                                         "hatches on the openings, the cavern seal)" if seal else
                                         "the AI walls the openings it finds and its squads and gates answer "
                                         "it when it comes near")
                         + ("" if seal or _d(s.get("settings")).get("seal_caverns") is not False
                            else " (sealing the caverns is off on the Rules tab)"))
        else:
            # (item7) said as the fort's own entrance map has it: B (13 Nov)
            # read "the AI walls the openings it finds" every cycle while the
            # map found no way down at all (the cavern joined the fort's walk
            # only through the cavern wells' lidded shafts)
            from planner_threats import cavern_way_state
            way, ents = cavern_way_state(s)
            if way == "none":
                notes.append(f"{c['name']} joins the fort's walk (z{c.get('z_bottom')}-{c.get('z_top')}){where_}, but "
                             "today's entrance map finds no way down from inside the fort (only the cavern wells' "
                             "lidded shafts, or across the surface behind the gates)")
            elif way == "closed":
                notes.append(f"{c['name']} is open to the fort's ground (z{c.get('z_bottom')}-{c.get('z_top')}){where_}: "
                             f"its {len(ents)} opening(s) are shut or being shut")
            else:
                notes.append(f"{c['name']} is open to the fort's ground (z{c.get('z_bottom')}-{c.get('z_top')}){where_}: "
                             "the AI walls or doors the openings it finds; cavern creatures can walk in until then")
    for x in dangers:
        if x.get("layer") in [c.get("name") for c in open_]:
            continue
        where = x.get("layer") or "the map"
        reach = " and can reach the dwarves" if x.get("can_reach_dwarves") else ""
        notes.append(f"{x.get('name')} ({x.get('kind')}) is in {where.replace('_', ' ')}{reach}")
    for c in [c for c in _l(d.get("cursed")) if isinstance(c, dict)]:
        if c.get("kind") == "vampire" and player_rules(s).get("expel_vampires", True):
            notes.append(f"{c.get('name')} is a vampire: the AI sends them away (Rules tab)")
        elif c.get("kind") == "vampire":
            # (0.105.35) the player's switch: kept, and said (not Needs you)
            notes.append(f"{c.get('name')} is a vampire: they drink sleeping dwarves' blood (dwarves die "
                         "drained, and the sheriff may convict the wrong one); sending vampires away is off on "
                         "the Rules tab, so the AI keeps them")
        elif _d(s.get("settings")).get("moon_cells") is not False:
            notes.append(f"{c.get('name')} carries a {c.get('kind')} curse: they change at the full moon and "
                         "attack: the AI locks them in a cell (a jail or a free bedroom) for the full moon")
        else:
            notes.append(f"{c.get('name')} carries a {c.get('kind')} curse: they change at the full moon and "
                         "attack; moon cells are off on the Rules tab, so the AI leaves them free and its squads "
                         "answer the beast")


ORDINALS = ("", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth")


def garden_name(s: dict, memory) -> str:
    """The fort's name (letters only), then "Second", "Third"... for later ones."""
    raw = str(_d(s.get("fort")).get("name") or "")
    base = " ".join("".join(ch for ch in w if (ch.isascii() and ch.isalpha()) or ch == "'")
                    for w in raw.split()).strip()
    base = " ".join(base.split()[:3]) or "Founders"
    n = len(memory.gardens_built or [])
    # (0.103.20) a name the season's character decision chose
    chosen = _d(getattr(memory, "culture", None)).get("set_piece_name")
    if isinstance(chosen, str) and chosen and chosen not in (memory.gardens_built or []):
        return chosen[:40]
    # (D0) the design language's words, when it has any (none at Scripts)
    words = [w for w in (_d(design.naming(getattr(memory, "culture", None))).get("words") or [])
             if isinstance(w, str) and w]
    if words:
        free = [w for w in words if w not in (memory.gardens_built or [])]
        if free:
            return free[0][:40]
        w = words[n % len(words)]
        k = n // len(words)
        return (w + (" " + ORDINALS[k] if 0 < k < len(ORDINALS) else ""))[:40]
    return (base + (" " + ORDINALS[n] if 0 < n < len(ORDINALS) else ""))[:40]


SOCIAL_KINDS = {"tavern": ("INN_TAVERN", ("BeWithFriends", "DrinkAlcohol", "Socialize"), "tavern_badly_per"),
                "temple": ("TEMPLE", ("PrayOrMeditate",), "temple_badly_per")}


def prayer_uncovered(s: dict) -> tuple[int, dict] | None:
    """(0.104.146) The dwarves distracted for want of prayer whose god no temple
    here serves (one to that god, to a religion that has it, or to all gods),
    and those by god: (n, {god: n}). None when the bridge doesn't say what the
    temples are dedicated to (older than 0.104.146), or there is no temple."""
    temples = [e for e in _l(_d(s.get("locations")).get("list")) if isinstance(e, dict) and e.get("type") == "TEMPLE"]
    if not temples or not any(("any_deity" in e or "deity_hf" in e or "religion_deities" in e) for e in temples):
        return None
    if any(e.get("any_deity") for e in temples):
        return 0, {}
    served = {e.get("deity_hf") for e in temples} | {h for e in temples for h in _l(e.get("religion_deities"))}
    nd = _d(s.get("needs"))
    ids = _d(nd.get("deity_ids"))
    by = {g: int(v or 0) for g, v in _d(nd.get("deities")).items() if ids.get(g) not in served}
    return sum(by.values()), by


def dining_shortfall(s: dict, cfg: dict) -> dict | None:
    """(0.104.135) The fort's tables against its diners, once it has a dining
    hall: {have, want, tables, citizens} when under `dining_short_share` of
    what it wants, or None.

    (0.105.51, R3 fort B) Public seats only: B had 29 tables for 83 dwarves,
    6 of them in its one dining hall (the rest in offices, nobles' dining
    rooms, the hospital), LackTables the worst stress (60+ citizens), and no
    hall came because all 29 were counted. With the bridge's table census
    (buildings.dining) only the tables in a dining hall nobody owns count,
    and the fort wants one for every `dining_seat_share` dwarf (half: meals
    are staggered). Eating without a table in the stress census
    (`lack_tables_min` citizens or more) is short too, while the halls seat
    under `lack_tables_seat_cap` of the fort (the census looks 28 days back:
    a hall just finished doesn't bring a third). `lack` and `source` say why."""
    zones = _d(_d(s.get("buildings")).get("zones"))
    if not zones.get("DiningHall"):
        return None                        # the first hall is the ladder's
    cit = int(_d(s.get("dwarves")).get("total") or 0)
    if cit < cfg["min_dwarves_for_dining"]:
        return None
    dn = _d(_d(s.get("buildings")).get("dining"))
    lack = 0
    for c in _l(_d(_d(s.get("needs")).get("stress_causes")).get("causes")):
        if isinstance(c, dict) and c.get("thought") == "LackTables":
            lack = int(c.get("citizens") or 0)
    lacking = lack >= cfg["lack_tables_min"]
    if isinstance(dn.get("hall"), int):
        have = dn["hall"]
        want = math.ceil(cit * cfg["dining_seat_share"])
        short = have < want or (lacking and have < math.ceil(cit * cfg["lack_tables_seat_cap"]))
        source = "public"
    else:                                  # an older bridge: every table the fort has
        have = int(_d(_d(s.get("buildings")).get("other")).get("Table") or 0)
        want = math.ceil(cit / cfg["dwarves_per_table"])
        short = (have < cfg["dining_short_share"] * want
                 or (lacking and have < math.ceil(cit * cfg["lack_tables_seat_cap"])))
        source = "all"
        if lacking:
            want = max(want, math.ceil(cit * cfg["dining_seat_share"]))
    if not short:
        return None
    return {"have": have, "want": want, "citizens": cit, "tables": max(8, min(40, want - have)),
            "lack": lack, "source": source}


def hospital_shortfall(s: dict, traits: dict, cfg: dict) -> dict | None:
    """(0.104.121) The hospitals' beds against the wounded resting (on the
    Rest job: in a bed, or on the hospital's floor when it has none free;
    Teacheroar's 5-bed hospital zone, a meeting hall, held 106 of 107):
    {unbedded, have, want, beds, citizens}, or None."""
    locs = _d(_d(s.get("locations")).get("count"))
    if not locs.get("HOSPITAL"):
        return None                      # the first hospital is the ladder's (and the urgent rule's)
    h = _d(s.get("health"))
    cit = max(1, int(_d(s.get("dwarves")).get("total") or 0))
    have = sum(int(_d(z).get("beds") or 0) for hosp in _l(h.get("hospital")) for z in _l(_d(hosp).get("zones")))
    if isinstance(h.get("resting"), int):
        resting = h["resting"]
    else:                                # an older bridge: the listed patients waiting for a treatment
        resting = sum(1 for p in _l(h.get("patients")) if isinstance(p, dict) and _l(p.get("needs")))
    unbedded = resting - have
    base = math.ceil(cit / 20 * factor(traits, "welfare")) + 2
    want = max(4, min(cfg["hospital_beds_max"], max(base, resting)))
    if unbedded < cfg["hospital_outside_min"] or have >= want:
        return None
    return {"unbedded": unbedded, "resting": resting, "have": have, "want": want, "citizens": cit,
            "beds": max(4, min(20, want - have))}

DIG_FIRST_KINDS = {"hospital", "tombs"}      # (0.104.128) levels dug before the rest


# (0.105.31) what a well's undug channel waits on (the bridge's well_check
# cause) -> what the AI does about it. (0.105.35) Said, not Needs you: nothing
# here waits for the player (was "what the player can do")
WELL_DIG_ASK = {
    "no_miners": "the AI's labour rules put dwarves on Mining (and the fort makes a pick when it has none)",
    "unreached": "the AI gives the spot up and picks another if no dwarf gets to it",
    "no_ground": "the AI gives the spot up and picks another",
    "marked": "the AI designates it a channel again (marker designations are never dug)",
    "wrong_designation": "the AI designates it a channel again",
    "unworked": "the AI renews the channel job at a higher priority; if still nothing, it gives the spot up "
                "and picks another",
    "no_designation": "the AI gives the spot up and picks another",
}


def _well_dig_rule(s: dict, memory, cfg: dict, p: dict, rec: dict, days: int, now: int,
                   proposals: list, notes: list | None) -> None:
    """(0.105.31) Wells nobody channels: shore wells in all six forts sat at
    "0 of 1 tiles dug" 14-80 days (E: a year, four times on one tile), a
    DigChannel job no miner took, and nothing could raise a channel. Its job
    renewed (well_renew_days, then weekly), and from dig_stall_days the
    cause said with what is being done (0.105.35: a note, not Needs you)."""
    dig = _d(p.get("dig"))
    if int(dig.get("dug") or 0) > 0:
        return
    chk = _d(dig.get("well_check"))
    cause = chk.get("cause")
    renewable = cause in (None, "unworked", "waiting", "wrong_designation", "marked")
    last = rec.get("renewed")
    if (renewable and days >= cfg["well_renew_days"]
            and (not isinstance(last, int) or now - last >= cfg["dig_raise_again_days"] * TICKS_PER_DAY)):
        pri = 1 if p.get("urgent") else 2
        proposals.append(Proposal("well_dig", {"type": "renew_well_dig", "project_id": p["id"], "priority": pri},
                                  f"the well level (project {p['id']}): its channel not dug in {days} days"
                                  + (f" ({chk.get('text')})" if chk.get("text") else "")
                                  + f": the channel job renewed at priority {pri}", 3))
        # (0.105.33) rec["renewed"] is set in planner.record once done: one
        # held by the cycle's limits is asked again
    if notes is not None and cause in WELL_DIG_ASK and days >= cfg["dig_stall_days"]:
        where = (f" at x{chk.get('x')} y{chk.get('y')} elevation {chk.get('elevation')}"
                 if chk.get("x") is not None else "")
        give_up = max(0, int(cfg["unreached_dig_days"]) - days)
        notes.append(f"the well's channel{where} hasn't been dug in {days} days: {chk.get('text') or cause}. "
                     f"{WELL_DIG_ASK[cause][0].upper()}{WELL_DIG_ASK[cause][1:]}"
                     + (f" (the spot is given up in {give_up} days)" if give_up else ""))


def _dig_stall_rule(s: dict, memory, cfg: dict, open_: list, proposals: list, notes: list | None = None) -> None:
    """(0.104.110, the 38-year soak) Teacheroar's tomb level sat at 235 of 240
    tiles for three game years ("5 being dug") and a bedroom level at 0 of 89
    for one, and with only two building slots nothing new was started from
    y76. A level with no tile dug for dig_stall_days: its dig jobs let go of
    their workers (a dwarf who took one and then lay in the hospital held it);
    still nothing after dig_stall_furnish_days and 90%+ dug: furnished
    without the last tiles."""
    now = abs_tick(s)
    seen = _d(memory.dig_seen)
    memory.dig_seen = seen
    live = set()
    for p in open_:
        if p.get("phase") != "dig" or not isinstance(p.get("id"), int):
            continue
        dig = _d(p.get("dig"))
        dug, total = int(dig.get("dug") or 0), int(dig.get("total") or 0)
        if total <= 0:
            continue
        k = str(p["id"])
        live.add(k)
        rec = seen.get(k)
        if not isinstance(rec, dict) or rec.get("dug") != dug:
            seen[k] = {"dug": dug, "tick": now}
            if isinstance(rec, dict) and rec.get("raised_ok"):
                seen[k]["raised_ok"] = rec["raised_ok"]    # (0.104.128) raised once is enough
            continue
        days = (now - int(rec.get("tick") or now)) // TICKS_PER_DAY
        what = f"the {p.get('kind')} level (project {p['id']})"
        if p.get("kind") == "well" and p.get("dig_done", "open") == "open":
            _well_dig_rule(s, memory, cfg, p, rec, days, now, proposals, notes)    # (0.105.31)
        # (0.104.128) dug first: an urgent level, or one with nothing dug for
        # weeks while other digging takes the miners (Teacheroar: the new
        # hospital 0 of 175, a bedrooms level 0 of 89 for years, at priority 4
        # with 260 tiles waiting elsewhere)
        raised = rec.get("raised_ok")
        # (0.104.134) asked again a week on while still nothing is dug (its
        # old jobs renewed at the new priority)
        again = isinstance(raised, int) and dug == 0 and now - raised >= cfg["dig_raise_again_days"] * TICKS_PER_DAY
        # (0.105.30 live fixes) never a well: its one tile is a channel on a
        # floor (dig_done "open"), and prioritize_dig raises only WALL tiles,
        # so every ask came back "nothing left to dig" (8 Nov: 119 refusals
        # in all six forts, "the well level: 0 of 1 tiles dug")
        if (dug < total and (not raised or again)      # (0.104.129: 0.104.128's "raised" marked held ones too)
                and p.get("kind") != "well"
                and (p.get("urgent") or p.get("kind") in DIG_FIRST_KINDS
                     or (dug == 0 and days >= cfg["dig_raise_days"]))):
            proposals.append(Proposal("dig_first", {"type": "prioritize_dig", "project_id": p["id"], "priority": 2},
                                      f"{what}: {dug} of {total} tiles dug"
                                      + (f", none for {days} days" if days else "")
                                      + ": dig it before the rest (priority 2)", 3))
            # (marked raised in planner.record, once the game took it: a
            # proposal held by the cycle's limits is asked again)
        jobs = "; ".join(str(w) for w in _l(dig.get("waiting"))[:3])
        # (0.105.48, K7c) never over a held or closed cavern shaft: the bridge refuses it
        shaft_shut = bool(dig.get("held")) or dig.get("shaft_open") is False
        if days >= cfg["dig_stall_furnish_days"] and dug >= 0.9 * total and dug < total and not shaft_shut:
            proposals.append(Proposal("project", {"type": "furnish_project", "project_id": p["id"], "stalled": True},
                                      f"{what}: {dug} of {total} tiles dug and none for {days} days"
                                      + (f" ({jobs})" if jobs else "") + ": furnish it without the last ones", 3))
        elif days >= cfg["dig_stall_days"] and int(dig.get("digging") or 0) > 0 and not rec.get("freed"):
            proposals.append(Proposal("dig_jobs", {"type": "free_dig_jobs", "project_id": p["id"]},
                                      f"{what}: no tile dug for {days} days though {dig.get('digging')} are "
                                      "taken" + (f" ({jobs})" if jobs else "") + ": let other miners take them", 3))
            # (0.105.33) rec["freed"] is set in planner.record once done
    for k in list(seen):
        if k not in live:
            del seen[k]


def _redig_rule(open_: list, proposals: list) -> None:
    """(0.105.48, K7c) A well's shaft or stairs, a gallery or a way in's steps
    that lost their designation (dig.redig_due in the report) are designated
    again by the redig_projects action. The report used to do it itself,
    every cycle and even while the AI was halted."""
    due = [p for p in open_ if p.get("phase") == "dig" and isinstance(p.get("id"), int)
           and int(_d(p.get("dig")).get("redig_due") or 0) > 0]
    if not due:
        return
    n = sum(int(_d(p.get("dig")).get("redig_due") or 0) for p in due)
    what = ", ".join(f"the {p.get('kind')} level (project {p['id']})" for p in due[:3])
    proposals.append(Proposal("redig", {"type": "redig_projects"},
                              f"{what}: {n} shaft, stair or gallery tile(s) lost their designation: "
                              "designate them again", 3))


def barracks_wanted(s: dict, traits: dict, memory) -> bool:
    """A militant fort (Militarism 50+), one with soldiers, or (r2 h8) one
    whose season's choice is barracks (R-F: 16 seasons of `raise:barracks`
    in a fort under Militarism 50 with no soldiers, and no barracks ever
    started: the choice could not act)."""
    if (traits.get("militarism", 0) or 0) >= 50 or _d(s.get("military")).get("soldiers"):
        return True
    if memory is None:
        return False
    try:
        import season
        return season.raised(memory, abs_tick(s)) == "barracks"
    except Exception:  # noqa: BLE001  (an odd memory: the old gate alone)
        return False


def room_size(traits: dict) -> int:
    """Fort size trait -> bedroom size: small 2x2, normal 3x3, large 4x4."""
    size = traits.get("size", 0)
    return 2 if size <= -50 else 4 if size >= 50 else 3


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


def more_temple(s: dict, traits: dict, cfg: dict):
    """(0.102.1) The god most of the fort's distracted dwarves pray to with
    no temple of their own, for a devout fort that has its first temple:
    (name, deity hf id, dwarves), or None. At most one temple per 50 Piety
    beyond the first. (0.105.23, 14.1 step 4b) At Piety `temple_god_piety`
    and up, the god most citizens pray to (met or not: the bridge's
    `worship`) with no temple of their own, once no distracted dwarves ask:
    the Monastery's temple per god (Piety 150 built one temple to all gods,
    and nobody was distracted enough to ask for more)."""
    piety = traits.get("piety", 0) or 0
    if piety < cfg["temple_more_piety"]:
        return None
    nd = _d(s.get("needs"))
    ids = _d(nd.get("deity_ids"))
    temples = [e for e in _l(_d(s.get("locations")).get("list")) if isinstance(e, dict) and e.get("type") == "TEMPLE"]
    if len(temples) >= 1 + int(piety // 50):
        return None
    # (0.105.23) a god served by a religion's temple has one too
    have = {e.get("deity_hf") for e in temples} | {h for e in temples for h in _l(e.get("religion_deities"))}
    for n, god in sorted(((int(v or 0), g) for g, v in _d(nd.get("deities")).items()), reverse=True):
        hf = ids.get(god)
        if n >= cfg["temple_more_worshippers"] and isinstance(hf, int) and hf not in have:
            return god, hf, n
    if piety >= cfg["temple_god_piety"]:
        for n, god in sorted(((int(v or 0), g) for g, v in _d(nd.get("worship")).items()), reverse=True):
            hf = ids.get(god)
            if n >= cfg["temple_god_worshippers"] and isinstance(hf, int) and hf not in have:
                return god, hf, n
    return None


def has_grand_temple(s: dict, memory) -> bool:
    """(0.105.23, 14.1 step 4b) The fort has a grand temple, or one under
    way: a temple complex (DF's tier 2), an open temple level dug grand, or
    a grand temple the AI started (remembered: the report keeps no size)."""
    if any(isinstance(e, dict) and e.get("type") == "TEMPLE" and int(e.get("tier") or 0) >= 2
           for e in _l(_d(s.get("locations")).get("list"))):
        return True
    if any(isinstance(p, dict) and p.get("kind") == "temple" and _d(p.get("summary")).get("temple") == "grand"
           for p in _l(_d(s.get("projects")).get("open"))):
        return True
    return bool(memory is not None and _d(getattr(memory, "culture", None)).get("grand_temple"))


def tombs_short(s: dict, citizens: int, cfg: dict, memory=None) -> int:
    """How many more free tombs the fort should have (0 if enough, or unknown)."""
    if "dead" in s.get("_errors", {}):
        return 0
    d = _d(s.get("dead"))
    unburied = int(d.get("unburied") or 0)
    why = _d(d.get("why"))
    if why and isinstance(why.get("free"), int):
        # (0.104.101) the bodies a hauler can take now, as the bridge counts them:
        # a body both outside and unreachable was subtracted twice (Teacheroar:
        # 27 unburied, 9 free, 14 outside, 18 out of reach -> 0, a 4-coffin level)
        unburied = int(why["free"]) + sum(int(why.get(k) or 0) for k in ("forbidden", "in_job", "carried"))
    elif why:
        # (0.104.38) only the bodies a tomb can take: Enxah's overnight run dug
        # 23 tomb levels for 35 bodies outside or out of reach, 71 tombs free
        unburied = max(0, unburied - sum(int(why.get(k) or 0) for k in ("outside", "unreachable", "not_ours", "dump")))
    want = max(cfg["min_free_tombs"], math.ceil(citizens * cfg["free_tombs_per_dwarf"])) + unburied
    if memory is not None and has_rule(memory.culture, "lay_the_dead"):
        want *= 2                                   # (0.103.1, Haunted)
    return max(0, want - (d.get("free_tombs") or 0))
