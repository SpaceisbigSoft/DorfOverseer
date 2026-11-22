"""The overseer's words: the one-line description of each action (short,
SHORT_WORDS), the co-pilot's big moves and answer ids, the camera feed and
the event and death lines. Split from overseer.py (r7 d1); overseer
re-exports every name.
"""

from __future__ import annotations

import hashlib
import json
import masterplan
from digest import _d

__all__ = ["MODES", "BIG_MOVES", "DECLINE_DAYS", "is_big", "ID_KEYS", "proposal_id", "CAMERA_QUIET",
           "FAILED_MOOD_WORDS", "journal_event", "death_words", "camera_feed", "SHORT_WORDS", "short"]


MODES = {"advisor": "Advisor", "copilot": "Co-pilot", "autopilot": "Autopilot"}
# What the co-pilot asks you about first (in the game's on-screen panel).
BIG_MOVES = {"start_project", "cancel_project", "cancel_work_order", "squad_fill", "import_orders",
             "build_gate_doors", "fortify_entrance", "expel_dwarf", "place_well", "link_lever", "place_traps",
             "remove_workshops", "deep_depot",      # (0.105.23) a wagon road and a hall dug
             "cut_entrance",                     # (0.105.0) hatches across the fort's stairs: asked first
             "build_gatehouse",                  # (0.105.23) walls and a drawbridge on the surface
             "place_hall", "build_wings",        # (0.105.30) a hall above ground; wall arms at the gatehouse
             "build_blueprint",                  # (D0) a landmark: asked first in co-pilot
             "place_garden_court"}               # (0.105.47) walls above ground by the fields
DECLINE_DAYS = 7          # a "No" holds this many in-game days before it may ask again


def is_big(action: dict) -> bool:
    return (action["type"] in BIG_MOVES or (action["type"] == "tool" and action.get("enabled") is False)
            # plots on existing floor are routine; digging a farm level is a project
            or (action["type"] == "farm_plots" and action.get("dig") is True))


ID_KEYS = ("type", "kind", "name", "size", "project_id", "order_id", "recipe", "squad_id")


def proposal_id(p) -> str:
    """Stable id for a proposal, so an answer in the game matches it next cycle.
    Sizes and counts are left out: a new bedroom level for 30 or for 32 rooms
    is the same question."""
    a = {k: p.action.get(k) for k in ID_KEYS if k in p.action}
    return hashlib.sha1((p.rule + json.dumps(a, sort_keys=True)).encode()).hexdigest()[:8]


CAMERA_QUIET = {"census", "join_levels", "dismiss_alerts", "sand_zone", "report_status", "survey_water", "scan_entrances", "recreation", "hospital_burrow",
                "calm_burrow",   # (0.104.169)
                "cistern_step", "water_work", "restrict_water", "save_memory", "pair_chairs", "approve_orders",
                "blueprint_sites",   # (D0) looks for sites, changes no tile
                # (0.105.40) world cleanup: nothing to look at
                "cleanup_items", "cleanup_units", "cleanup_spatter", "cleanup_dead_units",
                "insane_guard",   # (0.105.40b) doors locked and opened: nothing to look at
                "add_haulers", "relieve_haulers",
                "paint_traffic",   # (0.105.41) traffic designations: nothing to look at
                "clean_contaminants", "quarantine_syndromes", "clear_miasma"}   # (0.105.41, item 11) nothing to look at   # (0.105.40b fix) a work detail changed: nothing to look at


_CAMERA_LEVELS: list = []   # (0.104.91) the newest "dig a new ... level" lines, while the keeper runs


FAILED_MOOD_WORDS = {"berserk": "berserk"}      # melancholy and raving read plainly already ("in a melancholy mood")


def _victim_mood(ev: dict) -> str:
    """(0.105.30) The dead dwarf's own mood, said as theirs: "in a berserk
    mood" beside "by <killer>" read as if the killer was berserk (D and F,
    8 Nov). The killer's is `killer_mood` ("the killer ...")."""
    mood = str(ev.get("mood")).lower()
    if mood in FAILED_MOOD_WORDS:
        who = " ".join(str(ev.get("name") or "the dwarf").split()).split(",")[0]
        who = who.split(' "')[0].strip() or "the dwarf"
        return f"({who} was {FAILED_MOOD_WORDS[mood]} after a failed mood)"
    return f"in a {mood} mood"


def journal_event(ev: dict) -> dict:
    """(r1g8) The event as the journal keeps it: a death told again (a ghost
    laid to rest, the bridge's `again`) is kind "laid_to_rest", so no reader
    of the journal counts the dwarf dead twice."""
    if isinstance(ev, dict) and ev.get("kind") == "death" and ev.get("again"):
        return dict(ev, kind="laid_to_rest", was="death")
    return ev


def death_words(ev: dict) -> str:
    """(0.104.100) A death in a line: who, how (DF's cause), by whom, where."""
    who = " ".join(str(ev.get("name") or "someone").split())
    cause = str(ev.get("cause") or "").replace("_", " ").lower()
    bits = [who]
    if ev.get("again"):
        bits.append("(laid to rest: died before)" if not ev.get("ghost") else "(a ghost laid to rest)")
    elif cause:
        bits.append(cause)
    if ev.get("killer") and not ev.get("again"):
        bits.append(f"by {' '.join(str(ev['killer']).split())} ({ev.get('killer_kind') or '?'})")
    # (0.104.139) the fight's level, the killer's state and the victim's
    extra = [w for w in (ev.get("conflict") not in (None, "None") and f"a {str(ev['conflict']).lower()} fight",
                         ev.get("killer_mood") and f"the killer {str(ev['killer_mood']).lower()}",
                         # (0.105.24) which outsider: a visitor; or an old wound (the killer died first)
                         ev.get("killer_visitor") and "the killer a visitor",
                         ev.get("killer_dead") and "an old wound (the killer died before)",
                         ev.get("patient") and "a patient waiting for care",
                         ev.get("infected") and "infected",
                         # (0.104.148) the victim insane or in a mood (melancholy and raving dwarves stop drinking)
                         ev.get("mood") and _victim_mood(ev)) if w]
    if extra and not ev.get("again"):
        bits.append("; ".join(extra))
    if ev.get("x") is not None:
        bits.append(f"at x{ev['x']} y{ev['y']} z{ev['z']}")
    return ", ".join(bits)


def camera_feed(memory) -> dict:
    """(0.104.90) For the in-game camera: the plan's district names and the
    reasons for the AI's newest work (the camera shows them under a new or
    finished level of that kind). (0.104.91) Memory keeps only 10 actions and
    clearing alert icons crowded the levels out within a few cycles: the
    routine ones are left out, and each "dig a new ... level" line is kept
    here (4 at most) and put first, so a finished level's caption carries why
    it was dug too."""
    other = []
    for a in reversed(memory.recent_actions):
        act = a.get("action") if isinstance(a, dict) else None
        if not isinstance(act, dict) or act.get("type") in CAMERA_QUIET:
            continue
        line = f"{short(act)}: {a.get('reason', '')}".rstrip(": ")[:100]
        if act.get("type") == "start_project":
            if line not in _CAMERA_LEVELS:
                _CAMERA_LEVELS.insert(0, line)
                del _CAMERA_LEVELS[4:]
        elif line and line not in other:
            other.append(line)
    return {"districts": masterplan.camera_districts(memory), "news": (list(_CAMERA_LEVELS) + other)[:6]}


# (13c) The actions said the same way every time, for short() below.
SHORT_WORDS = {
    "blueprint_sites": "look for sites for a landmark",       # (D0) the Design track
    "build_blueprint": "start a landmark",
    "landmark_step": "build the landmark (next step)",
    "survey_water": "survey the water near the fort",
    "staff_labors": "give the hospital's staff the labours of their posts",
    "retarget_hall": "give a hall being dug to another petition",
    "dismiss_alerts": "clear old alert icons from the screen",
    "vacate_post": "give a patient's hospital post to a healthy dwarf",  # (0.104.111)
    "give_trinkets": "give trinkets to dwarves who want something to own",
    "place_keep": "build the keep above ground (next step)",
    "place_hall": "build the hall above ground (next step)",               # (0.105.30) construction
    "build_wings": "build wall arms out from the gatehouse",
    "floor_rooms": "lay block floors over a finished hall's soil",
    "deep_depot": "dig a wagon road down to an underground trade depot (next step)",  # (0.105.23)
    "polish": "smooth or engrave a finished level",
    "quarry": "dig a small quarry in ordinary stone",
    "adopt_uniform": "take charge of a squad's copied uniform",
    "idle_crafting": "let idle dwarves craft for themselves",
    "order_instrument": "order instruments for the tavern and temples",
    "slaughter_one": "send a spare animal to the butcher",
    "sand_zone": "make a sand collection zone (for glass)",
    "water_zone": "mark open water as a water source for the injured",
    "close_meeting": "leave DF's meeting screen",
    "answer_meeting": "answer the diplomat's meeting",  # (0.105.0)
    "prune_remains": "let old corpses and useless body parts rot away",
    "feeder_pile": "put a feeder stockpile beside a workshop",
    "food_pile": "put a food stockpile with barrels near the kitchen and still",   # (0.105.40b, M6)
    "food_barrels": "let the AI's food stockpile take barrels",
    "pile_barrows": "let the AI's stone stockpile take wheelbarrows",   # (0.105.41, item 2)
    "feeder_link": "link the AI's feeder stockpile to its workshop",
    "hunters": "send a hunter or two out after game (or call the AI's hunters in)",   # (0.105.41, item 4)
    "food_standing": "let the butchers, tanners and fishery work by themselves (DF's standing orders)",
    "fruit_zone": "mark the fruit trees near the fort for picking",
    "cavern_farm": "lay out farm plots on a cavern's soil",
    "fortify_post": "carve fortifications beside an entrance (archers shoot through them)",   # (item5)
    "archer_post": "post the crossbow squads behind the entrance's fortifications",
    "place_siege_engine": "place a ballista behind the entrance's fortifications",
    "place_siege_shop": "place a siege workshop (ballista parts and arrows), by the gate where there is room",
    "build_killzone": "set traps in the narrow way in behind a gate or cavern opening, and a drawbridge",   # (0.105.45)
    "reset_cage_traps": "see that the kill zone's full cage traps can be emptied and loaded again",
    "squad_barracks": "give a squad its barracks",
    "open_trade": "open the trade screen at the depot",
    "close_trade": "close the trade screen",
    "call_trader": "send someone to the trade depot",
    "place_slabs": "put up the engraved memorial slabs",
    "unload_depot": "take the fort's goods back out of the trade depot",
    "make_squad": "make a squad and appoint its leader",
    "gather_plants": "gather the shrubs near the fort",
    "unstick_uniforms": "untangle the soldiers' uniforms (uniform-unstick)",
    "free_stray_gear": "hand out the gear the game had lost track of",  # (0.104.58)
    "guard_gate": "send the squads to hold the main gate",  # (0.104.83)
    "gate_dogs": "pen the war dogs inside the main gate",  # (0.104.83)
    "train_war": "put tame animals to war training",  # (0.104.81)
    "nest_boxes": "pen the hens together and put nest boxes in their pasture",  # (0.104.80)
    "accept_cups": "let the finished goods piles take the loose cups",  # (0.104.168)
    "prisoner_room": "a cage room for the prisoners inside the fort",
    "make_pit": "a pit zone for the prisoners over a deep drop already there",  # (item6)
    "pit_prisoners": "send caged prisoners to the AI's pit",  # (item6)
    "traction_rest": "get a patient who needs traction out of an ordinary bed, so the game lays him on the traction bench",  # (0.105.24)
    "mood_free_items": "free the forbidden materials a strange mood is waiting for",  # (0.105.24)
    "add_doctor_post": "add a second doctor's post at a hospital",  # (0.104.168)
    "recreation": "move the unhappiest into the recreation burrow, the recovered back to work",  # (0.104.78)
    "pair_chairs": "put a chair beside each lone chair in the tavern",  # (0.104.77)
    "squad_swap": "send a soldier back to work and draft a keen dwarf in his place",  # (0.104.65)
    "assign_kit": "give the soldiers the free armour the game won't hand out",  # (0.105.8)
    "assign_weapons": "give the soldiers the free weapons the game won't hand out",  # (0.104.60)
    "assign_quivers": "give the crossbow soldiers quivers",
    "squad_bolts": "bolts for a crossbow squad",
    "assign_bolts": "hand the free bolts to the crossbow squads",   # (r2h4)
    "cut_entrance": "hatches on the stairs down from a wide opening",
    "farm_thresholds": "set which crops the farms favour (autofarm)",
    "pull_gate": "pull the AI gate lever",
    "clear_webs": "clear the spider webs",  # (0.104.116)
    "remove_webs": "remove spider webs far from the fort",  # (0.105.3)
    "mood_shelter": "let a strange mood's workshop and materials into the shelter",  # (0.105.47, J1)
    "scrub_dead_units": "clear old dead creatures from the game's unit list",  # (0.104.158)
    # (0.105.40, 13e) world cleanup (brain/planner_cleanup.py)
    "cleanup_items": "delete items no dwarf has reached for a year",
    "cleanup_units": "remove creatures no dwarf can reach (a season out of reach)",
    "cleanup_spatter": "clean blood and spatter off the map",
    "cleanup_dead_units": "take long-dead creatures off the game's active list",
    "insane_guard": "lock the AI's own doors between an insane dwarf and deep water, magma or a drop while they are near",  # (0.105.40b)
    "killer_cell": "lock a killer or a vampire among the fort's own in a cell (let out to eat and drink)",  # (item3)
    "stuck_reset": "take an AI lever's waiting pull job off (and ask the pull afresh)",  # (0.105.45)
    "thirst_unforbid": "let go the forbidden drink a parched dwarf can reach",  # (0.105.46, I2)
    "thirst_way": "open a parched dwarf's way to drink",  # (R1 g2)
    "thirst_patient": "get water to a parched patient",  # (R1 g2)
    "thirst_probe": "look into why a parched dwarf doesn't drink",  # (R1 g2)
    "well_safety": "keep the cavern wells safe: the watcher, the shaft's column, the gallery's door, the next level",  # (0.105.47)
    "well_rescue": "let a dwarf stranded in the cavern under a well back up (its door, or a stair dug out)",  # (0.105.47)
    "cross_cavern": "take the main stair down through the first cavern in a walled shaft",  # (0.105.47)
    "place_garden_court": "build the garden court by the fields (next step)",  # (0.105.47)
    "garden_court_meeting": "switch the garden court's meeting area off while danger is about, on once it has gone",  # (r9 c1)
    # (0.105.45) a great beast sealed in a cavern lured in and cut off (brain/planner_lure.py)
    "build_lure": "lay out a lure pocket behind a cavern door (cage traps, or drawbridges on levers)",
    "lure_open": "open the cavern door into the lure pocket (nobody below or near)",
    "lure_shut": "shut the lure pocket: lock the cavern door, raise its gates",
    "magma_reclaim": "open the paths again where spilt magma cooled, and dig out what it left",  # (0.105.41, item 7)
    "clean_contaminants": "clean a syndrome's spreading material off the dwarves and floors",   # (0.105.41, item 11)
    "quarantine_syndromes": "keep the carriers of a contact syndrome in the hospital",
    "clear_miasma": "mark what rots indoors for the garbage dump",
    "add_haulers": "put idle dwarves on hauling",  # (0.105.40 M5)
    "cavern_logging": "mark cavern trees for the woodcutters (or call them back)",  # (item10)
    "keep_grove": "keep a grove of young trees from the axes",  # (item10)
    "bench_caps": "make a second workshop a training bench (or lift its skill cap)",  # (item10)
    "relieve_haulers": "take key workers (or the AI's extra haulers) off hauling, or give it back",
    "paint_traffic": "mark high traffic on the AI's corridors and stairs, low on its rooms and fields",  # (0.105.41)
    "place_display": "build a pedestal or display case in one of the AI's temples, libraries, taverns or halls",  # (item 12)
    "display_artifact": "put one of the fort's artifacts on display behind doors",
    "hunt_send": "hunt: send squads after a beast or an enemy",   # (0.105.45)
    "hunt_recall": "hunt back: call the hunting squads home",    # (0.105.45)
    "call_migrants": "call a migrant wave (DFHack's force Migrants) to a fallen fort DF sends none to",  # (0.105.46, I4)
    "free_caravan": "tell the merchants of a caravan stuck leaving to walk off the map",  # (r2 h9)
    "open_meeting": "open the meeting waiting behind DF's diplomacy light",  # (0.105.47)
    "close_world": "leave DF's World screen",   # (0.105.48, K9) unattended backstop
    "hospital_guard": "station a calm squad in the hospital while a tantrum is loose (or take it off)",  # (0.105.47)
    "tantrum_step_down": "take a tantrum-thrower off every post and the hospital work",  # (0.105.47)
    "training_squad": "a squad that only trains, for the civilians who badly want to fight (made, filled with volunteers, or let go)",  # (0.105.47)
    "coffins_anywhere": "coffins with a tomb each on the AI's other levels, when no tomb level comes",  # (0.105.47, I7b)
    "engrave_memorials": "memorial slabs for the dead nobody can reach, before their ghosts rise",  # (0.105.47, I7b)
    "train_cook": "keep one cook at the kitchens so they learn",  # (0.105.47, I7b)
    "near_gates": "keep the civilians' work outside near the gates (or let it go anywhere again)",  # (0.105.47, I7d)
    "retire_water_zones": "take down the AI's water zones on surface water before the ice",  # (0.105.47, I7d)
    "census": "count what fills the map",  # (0.104.113)
    "seal_well_stairs": "close the cavern wells' stair columns",  # (0.104.151)
    "join_levels": "join areas on one level that meet only through the stairs",  # (0.104.108)
    "scan_entrances": "map the fort's entrances",
    "arm_gates": "watch the gates (close when danger nears)",
    "open_gates": "open the gates",
    "open_entrance": "open one gate for citizens shut out",
    "close_threatened_gates": "shut the gates an enemy is close to (the watcher failed)",   # (0.105.35)
    "free_gate_jobs": "resume the suspended jobs of a gate planned at an entrance",       # (0.105.35)
    "found_fort": "dig the fort's first staircase",
    "link_lever": "link the AI gate lever to a drawbridge or hatch",
    "place_gate_lever": "put a lever inside the fort for the gate",
    "build_gate_doors": "put doors on an open entrance",
    "expel_dwarf": "send a dwarf away",
    "release_prisoners": "let the jailed go (no water for them)",   # (item5)
    "setup_shelter": "set up the AI shelter burrow",
    "refresh_shelter": "make the AI shelter again (a gate was lost)",    # (0.105.26)
    "sync_offices": "put the appointed nobles on the game's duty lists",
    "polish_room": "smooth or engrave a noble's room up to their office's value",   # (0.105.41)
    "bootstrap_chair": "make one chair straight at a workshop (for the manager's office)",
    "approve_orders": "approve the AI's waiting work orders (no manager's office yet)",
    "unsuspend_orders": "resume the AI's suspended work-order jobs",
    "restrict_water": "mark the tiles over the water as restricted traffic",
    "free_slabs": "unforbid the memorial slabs and resume their building",
    "clear_orphan_jobs": "take jobs off the benches whose work order is gone",
    "repair_rooms": "build back the walls dug out of rooms",
    "allow_burial": "let the AI's tombs take the fort's dead",
    "unforbid_dead": "unforbid the fort's dead so they can be buried",
    # (0.105.27) forbidden items disposed of
    "unforbid_items": "unforbid the forbidden items worth keeping, so they are stored",
    "mark_melt": "mark surplus and worn metal to melt down",
    "mark_dump": "mark worn-out junk for the garbage dump",
    "place_dump": "make a garbage dump",
    "empty_dump": "remove the items piled in the garbage dump (DFHack)",
    "set_standing_orders": "set the game's standing orders",
    # (13c) planner actions that had no words (the panel showed their type)
    "break_fights": "end the citizens' fights (fix/loyaltycascade)",
    "build_crossing": "build a bridge across a gap",
    "remove_crossing": "take down one of the AI's bridges",
    "free_dig_jobs": "free the workers held by a stalled level's dig jobs",
    "renew_well_dig": "renew a well's channel job nobody takes",   # (0.105.31)
    "redig_projects": "designate a level's lost shaft, stair or gallery tiles again",   # (0.105.48)
    "unmark_project_dig": "make a level's marker-only dig tiles real",   # (0.105.35)
    "trim_instrument_orders": "cancel extra instrument orders",
}
# (0.105.47) the herd by Husbandry (lua/ai-herd.lua, brain/planner_husbandry.py)
SHORT_WORDS.update({
    "herd_breeders": "keep a breeding male and females of each kind from the butcher",
    "tame_wild": "have the animal trainers tame caged wild animals",
    "train_hunt": "put tame animals to hunting training",
    "herd_targets": "set how many of each kind autobutcher keeps",
})
# (0.105.47) a mission's travellers let out (lua/ai-mission-way.lua)
SHORT_WORDS.update({
    "mission_way": "open one of the AI's gates so a mission can leave the map",
    "way_out_open": "open one of the AI's gates: the fort was sealed in",
    "way_out_leave": "leave the fort open as the AI stops",
})
# (0.105.47, J17) a raid party's pets (lua/ai-raids.lua)
SHORT_WORDS.update({
    "mission_pets": "let soldiers' pets out of a pasture for a mission, or put them back",
})


def short(a: dict) -> str:
    """An action in a few words, for the on-screen panel."""
    t = a.get("type")
    if t == "found_fort" and a.get("wide"):      # (0.105.35)
        return "dig the first staircase, further from the wagon"
    words = SHORT_WORDS.get(t)
    if words is not None:
        return words
    if t == "set_population_cap":
        return f"set the population cap to {a.get('cap')}"
    if t == "unstick_gate":          # (0.105.32) an open gate the game holds shut; the step in the words
        return f"free a gate the game holds shut (step {a.get('step') or 1} of 3)"
    if t == "dig_way_in" and a.get("second"):     # (0.105.33)
        return "dig a second way in from the surface"
    if t == "dig_way_in" and a.get("cave_in"):    # (0.105.41 review) the cave-in dig-out's own words
        return "dig a way to the dwarves a cave-in cut off"
    if t == "dig_way_in":            # (0.105.32)
        return "dig a stair in for the citizens cut off outside"
    if t == "work_order":
        return f"order {a.get('amount')} x {str(a.get('recipe')).replace('_', ' ')}"
    if t == "tool":
        return f"{a.get('name')} {'on' if a.get('enabled') else 'off'}"
    if t == "civ_alert":
        return f"civilian alert {'on' if a.get('on') else 'off'}"
    if t == "weather_burrow":        # (item4) evil weather: kept in without the alarm
        return ("keep the civilians inside, out of the evil weather (no alarm)" if a.get("on")
                else "let the civilians kept in for the weather back outside")
    if t == "squad_fill":
        return f"add {a.get('count')} soldiers to a squad"
    if t == "squad_orders":
        return "call the squad back" if a.get("clear") else f"send a squad at {len(a.get('kill') or [])} enemies"
    if t == "squad_routine":
        return f"squad on {str(a.get('routine')).lower()}"
    if t == "assign_labor":
        return (f"put {a.get('count')} more dwarves on {a.get('job')}" if a.get("count")
                else "put the work details in order")
    if t == "place_surface":
        return {"refuse": "put a refuse pile outside", "dump": "make a garbage dump outside",
                "cages": "make a stockpile for full cages"}.get(
            a.get("kind"), "build a trade depot outside")
    if t == "cistern_step":
        if a.get("retire"):      # (0.105.35)
            return "retire the cistern (its floodgate shut)"
        if a.get("relink"):
            return "the cistern: ask for its lever link afresh"
        return "shut the cistern's floodgate" if a.get("shut") else "the cistern: next step"
    if t == "water_work":        # (0.105.0)
        what = {"moat": "the moat", "pump": "the pump stack", "irrigation": "the muddied farm level",
                "magma": f"the {a.get('shop') or 'magma workshop'}",
                "power": "the pump stack's power"}.get(a.get("kind"), "a water work")   # (0.105.37 E3)
        if a.get("kind") == "power" and a.get("shut"):
            return "switch off the pump stack's power"
        if a.get("shut"):
            return f"shut {what}'s floodgate"
        if a.get("retire"):      # (0.105.35)
            return f"retire {what} (its floodgate shut)"
        if a.get("reopen"):      # (0.105.36)
            return f"open {what}'s floodgate again (the flood is over)"
        if a.get("recheck"):     # (0.105.36)
            return f"{what}: look again at its leak watch"
        return f"{what}: next step"
    if t == "answer_petition":
        if a.get("ids"):
            return ("agree to" if a.get("accept") else "decline") + f" {len(a['ids'])} petitions to stay"
        if a.get("residency"):
            return ("agree to" if a.get("accept") else "decline") + " a petition to stay"
        return ("agree to" if a.get("accept") else "decline") + " a petition for a temple or guildhall"
    if t == "place_in_zone":
        return f"put {str(a.get('what') or 'furniture').replace('_', ' ')} in a zone"
    if t == "petition_orders":
        return "answer petitions: " + ", ".join(
            f"{'accept' if v else 'ask about'} {str(k).replace('_', ' ')}" for k, v in (a.get("orders") or {}).items())
    if t == "add_posts":
        return "make posts at a location (" + ", ".join(str(k).lower().replace("_", " ") for k in (a.get("posts") or [])) + ")"
    if t == "staff_location":
        return f"give a dwarf the {str(a.get('post') or 'post').lower().replace('_', ' ')} post"
    if t == "house_dwarves":     # (0.104.168)
        return ("move stressed dwarves to rooms they like better" if not a.get("house")
                else "one bedroom per household (couples together, a room for those with none)")
    if t == "furnish_liked":     # (E4)
        return "furnish citizens' rooms with pieces they like"
    if t == "remove_workshops":
        return f"take down extra {a.get('kind')} workshops"
    if t == "trim_gathering":
        return f"cancel waiting plant-gathering jobs, keeping {a.get('keep')}"
    if t == "allow_stone":
        stone = str(a.get('stone')).lower().replace('_', ' ')
        return f"keep {stone} from the masons" if a.get("keep") else f"let the masons use {stone}"
    if t == "set_uniform_weapon":
        return f"arm a squad with {str(a.get('weapon')).replace('ITEM_WEAPON_', '').lower().replace('_', ' ')}s"
    if t == "set_uniform":
        return f"give a squad the {a.get('kind')} {'crossbow ' if a.get('ranged') else ''}uniform"
    if t == "give_room":
        return f"give {a.get('name') or 'a noble'} a {a.get('kind')}"
    if t == "trim_labor":
        return f"take all but {a.get('keep')} off the {a.get('job')} work detail"
    if t == "narrow_detail":
        return f"{'widen' if a.get('widen') else 'narrow'} the {a.get('job')} work detail"
    if t == "send_mission":      # (0.105.24, 13b; 0.105.39 the other goals)
        if a.get("goal") in (None, "make_contact"):
            return f"send the messenger to make contact with site {a.get('site_id')} (World screen)"
        from planner_missions import MISSION_WORDS
        n = len(a.get("squad_ids") or [])
        return (f"send {n} squad{'s' if n != 1 else ''} to {MISSION_WORDS.get(a.get('goal'), str(a.get('goal')))} "
                f"at site {a.get('site_id')} (World screen)")
    if t == "keep_mousers":      # (0.104.168)
        return f"keep {a.get('count') or 'a few'} cats from the butcher to hunt the vermin"
    if t == "trade_deal":
        return "trade with the caravan" + (" (and press Trade)" if a.get("press") else "")
    if t == "bring_goods":
        return f"take {a.get('count')} crafts to the trade depot"
    if t == "kitchen_skill":
        return (f"let only cooks of skill {a.get('min_level')}+ work the kitchens" if a.get("min_level") else
                "let any cook work the kitchens again")
    if t == "clear_gate":
        return f"take down the gate at x{a.get('x')} y{a.get('y')}"
    if t == "mine_ore":
        return f"mine a vein of {str(a.get('metal')).lower()} ore"
    if t == "appoint":
        return f"appoint a {str(a.get('office')).lower().replace('_', ' ')}"
    if t == "dig_stairwell":     # (0.104.82)
        return f"dig a new stairwell {a.get('dir')} of the main stair"
    if t == "hospital_burrow":   # (0.104.167)
        if a.get("release"):
            return "let every patient out of the hospital burrow"
        return "keep the wounded inside the hospital, the healed back to work"
    if t == "calm_burrow":       # (0.104.169)
        if a.get("release"):
            return "let every dwarf out of the calm-down burrows"
        return "keep each dwarf in a tantrum in a free bedroom away from the patients till calm, the calm let out"
    # (0.105.0) round 3: threats answered
    if t == "fire_guard":
        return "the fire is out: paths round it back to normal" if a.get("lift") else "keep the dwarves away from the fire"
    if t == "magma_guard":    # (0.105.41, item 7)
        return "paths round the spilt magma back to normal" if a.get("lift") else "keep the dwarves away from the spilt magma"
    if t == "moon_cell":
        return "let the werebeasts out of their cells" if a.get("release") else "lock the werebeasts in for the full moon"
    if t == "seal_cavern":
        if a.get("openings") or a.get("layer") == "all caverns":       # (0.105.26) every cavern opening
            return "open the ways into the caverns again" if a.get("open") else "lock every way into the caverns"
        return f"unlock the way down to {a.get('layer')}" if a.get("open") else f"lock the way down to {a.get('layer')}"
    if t == "rest_infected":     # (0.104.168)
        return f"put up to {a.get('max', 3)} dwarves with infected wounds to bed in the hospital, for the doctors"
    # (0.105.0, round 2) an army that can fight
    if t == "fix_gear_gaps":
        return "mend the uniforms so the soldiers get weapons" + (" and shields" if a.get("shields") else "")
    if t == "shelter_squads":
        st = a.get("station") if isinstance(a.get("station"), dict) else None   # (0.105.45)
        if st:
            return (f"station {len(a.get('squads') or [])} squad(s) at x{st.get('x')} y{st.get('y')} z{st.get('z')}, "
                    "between the threat and the civilians' shelter")
        return f"send {len(a.get('squads') or [])} squad(s) to wait in the shelter"
    if t == "shelter_pick":        # (0.105.45)
        if a.get("clear"):
            return "draw the civilians' shelter over the whole fort again"
        return f"draw the civilians' shelter over level(s) {', '.join(str(z) for z in a.get('levels') or [])}, away from the threat"
    if t == "squad_station":       # (0.105.45)
        return f"station squad {a.get('squad_id')} at x{a.get('x')} y{a.get('y')} z{a.get('z')}"
    if t == "set_farm_crops":      # (0.105.5) Hammerstirred: the plots lay fallow under autofarm
        return ("set each farm plot's crops" + (" (brewable first)" if a.get("drink") else "")
                + (" (a second brewable crop: drinks of more kinds)" if a.get("variety") else ""))
    if t == "kitchen_brewables":   # (0.100) the kitchen ban on cooking brewables
        return ("stop the kitchen cooking brewable plants" if a.get("ban") else
                "let the kitchen cook brewable plants again")
    if t == "set_rules":         # (0.105.20) logs/rules-request.json
        return "set Rules switches: " + ", ".join(f"{k} {('on' if v else 'off') if isinstance(v, bool) else v}"
                                                   for k, v in sorted(_d(a.get("rules")).items()))
    if t == "apply_preset":      # (0.105.4) keeper.py --preset
        return f"apply the {a.get('name')} preset"
    if t == "convict":           # (0.104.131)
        return f"convict {a.get('max')} solved case(s)"
    if t == "well_shaft":        # (0.104.152)
        words = "shut the cavern well's shaft" if a.get("close") else "the cavern well's shaft gate: its next step"
        if a.get("dry") is not None:      # (group 2) the fort short of water, or not
            words += " (short of water: a far walker doesn't keep it shut)" if a.get("dry") else " (water again)"
        return words
    if t == "prioritize_dig":    # (0.104.128)
        return f"dig level {a.get('project_id')} before the rest"
    if t == "mark_run":          # (0.105.0)
        return f"mark this save as test run {a.get('run_id')}"
    if t == "place_traps":
        return f"put {a.get('count')} {a.get('kind')} traps behind a gate"
    if t == "build_gatehouse":     # (0.105.23, 14.1 step 4a)
        if a.get("count") == 0:        # (0.105.51) every fort's plain one
            return "build a gatehouse at the founding stair (a drawbridge at the end of a walled corridor)"
        return f"build a gatehouse at the founding stair (drawbridge, walls, {a.get('kind') or 'cage'} trap corridor)"
    if t == "location_access":
        return ("open" if a.get("visitors") else "close") + f" {len(a.get('ids') or [])} location(s) to visitors"
    if t == "fortify_entrance":
        if a.get("style") == "sealed":         # (0.105.30) the Hermit's cavern walls
            return "wall a narrow cavern opening shut"
        if a.get("style") == "wagon":          # (0.105.30) the deep depot's road
            return "put a drawbridge across the depot's wagon road"
        return f"wall an entrance down to a {a.get('style')} gate"
    if t == "pasture":
        return f"put {a.get('count')} animals in a pasture"
    if t == "import_orders":
        return f"add DFHack's {a.get('library')} orders"
    if t == "make_pasture":
        return f"make a {a.get('tiles')}-tile pasture"
    if t == "place_well":
        return ("dig a shaft to a cavern lake for a well" if a.get("cavern")
                else "dig a winter cistern and a well over it" if a.get("filled") else "dig a well over water")
    if t == "farm_plots":
        return (f"lay out {a.get('tiles')} farm tiles" + (" underground" if a.get("underground") else "")   # (0.105.5)
                + (" (or dig a farm level)" if a.get("dig") else ""))
    if t == "start_project":
        what = a.get("name") and f"memorial for {a['name']}" or a.get("kind")
        return f"dig a new {what} level"
    if t == "finish_project" and a.get("leave_planned"):       # (r2h7)
        return f"close level #{a.get('project_id')}, its waiting pieces left planned"
    if t == "finish_project" and a.get("give_up") and a.get("drop"):       # (R2 h3)
        return f"finish level #{a.get('project_id')} without its waiting {', '.join(str(x) for x in a['drop'])}"
    if t == "finish_project" and a.get("give_up"):       # (0.105.51)
        return f"finish level #{a.get('project_id')} without its waiting workshops"
    if t == "park_project":                              # (R2 h3)
        return f"let level #{a.get('project_id')} wait for its pieces without a building slot"
    if t in ("furnish_project", "finish_project", "engrave_project", "cancel_project"):
        return f"{t.split('_')[0]} level #{a.get('project_id')}"
    if t == "cancel_work_order":
        return f"cancel order #{a.get('order_id')}"
    if t == "quick_location":
        return f"make the dining hall a {a.get('kind')} for now"
    if t == "squad_release":
        return f"take unit {a.get('unit_id')} out of the squad"
    if t == "squad_trim":
        return f"send {a.get('count')} soldier(s) back to work"
    if t == "seed_reserve":   # (r2h6)
        return ("keep " + ", ".join(str(x).lower() for x in (a.get("ban") or [])[:3]) + " and its seed from the cooks"
                if a.get("ban") else "let the cooks use the plants whose seed has come back")
    if t == "kitchen_fat":
        return "keep fat and tallow from the cooks" if a.get("ban") else "let the cooks use fat and tallow again"
    if t == "order_slots":
        return f"let workshop #{a.get('workshop_id')} take {a.get('max')} jobs from work orders"
    if t == "bench_jobs":
        return f"put {a.get('count')} {a.get('kind')} job(s) straight on a workshop's bench"
    return str(t)
